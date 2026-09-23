"""Paged texture array: original image can exceed GL_MAX_TEXTURE_SIZE."""
import math
import queue
import threading

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import numpy as np
from PIL import Image
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader

from .projection import camera_basis
from .model import atlas_layout


VERTEX = '''#version 330 core
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
'''

FRAGMENT = '''#version 330 core
out vec4 color;
uniform sampler2DArray pages;
uniform isampler2D ready;
uniform vec2 viewportSize;
uniform ivec2 imageSize;
uniform int pageSize;
uniform int pageColumns;
uniform vec3 cameraRight, cameraUp, cameraForward;
uniform float tanHalfFov, azimuthOrigin, topLatitude, latitudeSpan;
const float PI = 3.141592653589793;

vec3 pixel(ivec2 p) {
    p.x = (p.x % imageSize.x + imageSize.x) % imageSize.x;
    p.y = clamp(p.y, 0, imageSize.y - 1);
    ivec2 page = p / pageSize;
    if (texelFetch(ready, page, 0).r == 0) return vec3(0.08, 0.105, 0.14);
    return texelFetch(pages, ivec3(p % pageSize, page.y * pageColumns + page.x), 0).rgb;
}

void main() {
    vec2 p = 2.0 * gl_FragCoord.xy / viewportSize - 1.0;
    p.x *= viewportSize.x / viewportSize.y;
    vec3 ray = normalize(cameraForward + tanHalfFov * (p.x * cameraRight + p.y * cameraUp));
    float phi = atan(ray.x, ray.z);
    float theta = asin(clamp(ray.y, -1.0, 1.0));
    vec2 uv = vec2(fract((phi - azimuthOrigin) / (2.0 * PI)), (topLatitude - theta) / latitudeSpan);
    if (uv.y < 0.0 || uv.y > 1.0) { color = vec4(17.0/255.0, 22.0/255.0, 29.0/255.0, 1.0); return; }
    vec2 source = uv * vec2(imageSize) - 0.5;
    ivec2 base = ivec2(floor(source));
    vec2 f = fract(source);
    // Manual bilinear interpolation also crosses atlas pages and the 360° seam.
    vec3 upper = mix(pixel(base), pixel(base + ivec2(1, 0)), f.x);
    vec3 lower = mix(pixel(base + ivec2(0, 1)), pixel(base + ivec2(1, 1)), f.x);
    color = vec4(mix(upper, lower, f.y), 1.0);
}
'''


class PanoramaArea(Gtk.GLArea):
    def __init__(self, memory_mib, on_status, on_error, on_view):
        super().__init__()
        self.set_required_version(3, 3)
        self.set_use_es(False)
        self.set_auto_render(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(True)
        self.memory_mib = memory_mib
        self.on_status, self.on_error, self.on_view = on_status, on_error, on_view
        self.panorama = None
        self.program = self.vao = self.texture = self.ready_texture = None
        self.yaw, self.pitch, self.fov = 0., 0., 60.
        self.stop_worker = threading.Event()
        self.upload_source = None
        self.snapshot_path = None
        self.connect('realize', self._realize)
        self.connect('unrealize', self._unrealize)
        self.connect('render', self._render)

    def _realize(self, area):
        self.make_current()
        if self.get_error():
            self.on_error(str(self.get_error()))
            return
        try:
            self.program = compileProgram(compileShader(VERTEX, GL.GL_VERTEX_SHADER),
                                          compileShader(FRAGMENT, GL.GL_FRAGMENT_SHADER), validate=False)
            self.vao = GL.glGenVertexArrays(1)
            if self.panorama:
                self.load(self.panorama)
        except Exception as error:
            self.on_error(f'OpenGL: {error}')

    def _cancel(self):
        self.stop_worker.set()
        if self.upload_source is not None:
            GLib.source_remove(self.upload_source)
            self.upload_source = None

    def _delete_textures(self):
        for value in (self.texture, self.ready_texture):
            if value is not None:
                GL.glDeleteTextures([value])
        self.texture = self.ready_texture = None

    def _unrealize(self, area):
        self._cancel()
        self.make_current()
        if self.get_error():
            return
        self._delete_textures()
        if self.program:
            GL.glDeleteProgram(self.program)
            self.program = None
        if self.vao:
            GL.glDeleteVertexArrays(1, [self.vao])
            self.vao = None

    def set_view(self, yaw=None, pitch=None, fov=None):
        if yaw is not None:
            self.yaw = yaw % 360
        if fov is not None:
            self.fov = max(15., min(110., fov))
        if pitch is not None:
            self.pitch = max(-89.9, min(89.9, pitch))
        self.on_view(self.yaw, self.pitch, self.fov)
        self.queue_render()

    def load(self, panorama):
        self.panorama = panorama
        self.set_view(panorama.default_yaw, panorama.default_pitch, panorama.default_fov)
        if not self.program:
            return
        self._cancel()
        self.make_current()
        self._delete_textures()
        try:
            self.layout = atlas_layout(panorama.level.width, panorama.level.height, self.memory_mib,
                                       int(GL.glGetIntegerv(GL.GL_MAX_TEXTURE_SIZE)),
                                       int(GL.glGetIntegerv(GL.GL_MAX_ARRAY_TEXTURE_LAYERS)))
            side, scale, width, height, cols, rows = self.layout
            self.texture = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, self.texture)
            GL.glTexParameteri(GL.GL_TEXTURE_2D_ARRAY, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D_ARRAY, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
            GL.glTexImage3D(GL.GL_TEXTURE_2D_ARRAY, 0, GL.GL_RGB8, side, side, cols * rows,
                            0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, None)
            self.ready_texture = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.ready_texture)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_R32I, cols, rows, 0, GL.GL_RED_INTEGER,
                            GL.GL_INT, np.zeros((rows, cols), dtype=np.int32))
        except Exception as error:
            self._delete_textures()
            self.on_error(f'Не удалось создать текстуру: {error}. Попробуйте --gpu-memory 128.')
            return

        self.stop_worker = threading.Event()
        messages = queue.Queue(maxsize=3)
        stop = self.stop_worker
        self.loaded_pages = 0
        self.failed_tiles = set()
        self.on_status(f'Загрузка {panorama.title}…')

        def put(message):
            while not stop.is_set():
                try:
                    messages.put(message, timeout=.1)
                    return
                except queue.Full:
                    pass

        def decode():
            try:
                for row in range(rows):
                    for col in range(cols):
                        if stop.is_set():
                            return
                        # Global boundaries are used when downsampling, so the
                        # final partial page has the same mapping as all others.
                        left = round(col * side * panorama.level.width / width)
                        top = round(row * side * panorama.level.height / height)
                        out_w, out_h = min(side, width-col*side), min(side, height-row*side)
                        right = round((col*side+out_w) * panorama.level.width / width)
                        bottom = round((row*side+out_h) * panorama.level.height / height)
                        page, failures = panorama.read_region(left, top, right-left, bottom-top)
                        if page.size != (out_w, out_h):
                            page = page.resize((out_w, out_h), Image.Resampling.LANCZOS)
                        put((col, row, out_w, out_h, page.tobytes(), failures))
            except Exception as error:
                put(error)

        def upload():
            try:
                message = messages.get_nowait()
            except queue.Empty:
                return True
            if isinstance(message, Exception):
                self.on_error(f'Ошибка загрузки тайлов: {message}')
                self.upload_source = None
                return False
            try:
                self.make_current()
                col, row, out_w, out_h, pixels, failures = message
                GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
                GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, self.texture)
                GL.glTexSubImage3D(GL.GL_TEXTURE_2D_ARRAY, 0, 0, 0, row*cols+col,
                                   out_w, out_h, 1, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, pixels)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self.ready_texture)
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, col, row, 1, 1, GL.GL_RED_INTEGER,
                                   GL.GL_INT, np.array([1], dtype=np.int32))
                self.failed_tiles.update(failures)
                self.loaded_pages += 1
                self.on_status(f'{panorama.level.width} × {panorama.level.height} · уровень {panorama.level.number}'
                               f' · текстура 1:{scale} · {self.loaded_pages}/{cols*rows}'
                               f' · отсутствуют/повреждены: {len(self.failed_tiles)}')
                self.queue_render()
            except Exception as error:
                self.stop_worker.set()
                self.on_error(f'Ошибка OpenGL: {error}')
                self.upload_source = None
                return False
            if self.loaded_pages == cols*rows:
                self.upload_source = None
                return False
            return True

        threading.Thread(target=decode, daemon=True).start()
        self.upload_source = GLib.timeout_add(10, upload)

    def _render(self, area, context):
        GL.glClearColor(.065, .086, .114, 1)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if not self.program or not self.texture or not self.ready_texture:
            return True
        viewport = GL.glGetIntegerv(GL.GL_VIEWPORT)
        width, height = int(viewport[2]), int(viewport[3])
        if width <= 0 or height <= 0:
            return True
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glUseProgram(self.program)
        GL.glBindVertexArray(self.vao)
        def uniform(name):
            return GL.glGetUniformLocation(self.program, name)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, self.texture)
        GL.glUniform1i(uniform('pages'), 0)
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.ready_texture)
        GL.glUniform1i(uniform('ready'), 1)
        side, _, w, h, cols, _ = self.layout
        GL.glUniform2f(uniform('viewportSize'), width, height)
        GL.glUniform2i(uniform('imageSize'), w, h)
        GL.glUniform1i(uniform('pageSize'), side)
        GL.glUniform1i(uniform('pageColumns'), cols)
        for name, vector in zip(('cameraRight', 'cameraUp', 'cameraForward'), camera_basis(self.yaw, self.pitch)):
            GL.glUniform3f(uniform(name), *vector)
        GL.glUniform1f(uniform('tanHalfFov'), math.tan(math.radians(self.fov) / 2))
        GL.glUniform1f(uniform('azimuthOrigin'), self.panorama.azimuth_origin)
        GL.glUniform1f(uniform('topLatitude'), self.panorama.top)
        GL.glUniform1f(uniform('latitudeSpan'), self.panorama.span)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        if self.snapshot_path:
            try:
                GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
                pixels = GL.glReadPixels(0, 0, width, height, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
                Image.frombytes('RGB', (width, height), pixels).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(self.snapshot_path, format='PNG')
            except Exception as error:
                self.on_error(f'Не удалось сохранить снимок: {error}')
            finally:
                self.snapshot_path = None
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)
        return True
