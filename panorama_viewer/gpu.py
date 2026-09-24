#!/usr/bin/env python3
"""OpenGL resources and rendering, independent of GTK widgets."""
import math
import numpy as np
from PIL import Image
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader
from .atlas import AtlasLayout
from .projection import SphericalProjection
from .shaders import ShaderSources
from .sky_shader import SkyUniforms


class ShaderProgram:
    def __init__(self):
        self.handle = compileProgram(compileShader(ShaderSources.VERTEX, GL.GL_VERTEX_SHADER),
                                     compileShader(ShaderSources.FRAGMENT, GL.GL_FRAGMENT_SHADER), validate=False)
        self.locations = {}

    def location(self, name):
        if name not in self.locations:
            self.locations[name] = GL.glGetUniformLocation(self.handle, name)
        return self.locations[name]

    def integer(self, name, value):
        GL.glUniform1i(self.location(name), value)

    def scalar(self, name, value):
        GL.glUniform1f(self.location(name), value)

    def integer_pair(self, name, first, second):
        GL.glUniform2i(self.location(name), first, second)

    def float_pair(self, name, first, second):
        GL.glUniform2f(self.location(name), first, second)

    def vector(self, name, values):
        GL.glUniform3f(self.location(name), *values)

    def close(self):
        if self.handle is not None:
            GL.glDeleteProgram(self.handle)
            self.handle = None


class TextureAtlas:
    def __init__(self, layout):
        self.layout = layout
        self.pages = self.ready = None
        try:
            self._allocate_pages()
            self._allocate_readiness()
        except Exception:
            self.close()
            raise

    @staticmethod
    def _texture(target):
        handle = GL.glGenTextures(1)
        GL.glBindTexture(target, handle)
        GL.glTexParameteri(target, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
        GL.glTexParameteri(target, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
        return handle

    def _allocate_pages(self):
        layout = self.layout
        self.pages = self._texture(GL.GL_TEXTURE_2D_ARRAY)
        GL.glTexImage3D(GL.GL_TEXTURE_2D_ARRAY, 0, GL.GL_RGB8, layout.side, layout.side,
                        layout.columns * layout.rows, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, None)

    def _allocate_readiness(self):
        layout = self.layout
        self.ready = self._texture(GL.GL_TEXTURE_2D)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_R32I, layout.columns, layout.rows, 0,
                        GL.GL_RED_INTEGER, GL.GL_INT, np.zeros((layout.rows, layout.columns), dtype=np.int32))

    def upload(self, page):
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, self.pages)
        layer = page.row * self.layout.columns + page.column
        GL.glTexSubImage3D(GL.GL_TEXTURE_2D_ARRAY, 0, 0, 0, layer, page.width, page.height,
                           1, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, page.pixels)
        self._mark_ready(page)

    def _mark_ready(self, page):
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.ready)
        GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, page.column, page.row, 1, 1,
                           GL.GL_RED_INTEGER, GL.GL_INT, np.array([1], dtype=np.int32))

    def bind(self, program):
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D_ARRAY, self.pages)
        program.integer('pages', 0)
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.ready)
        program.integer('ready', 1)

    def close(self):
        for texture in (self.pages, self.ready):
            if texture is not None:
                GL.glDeleteTextures([texture])
        self.pages = self.ready = None


class GpuRenderer:
    def __init__(self):
        self.program = ShaderProgram()
        self.vertex_array = GL.glGenVertexArrays(1)
        self.atlas = None

    def prepare(self, panorama, memory_mib):
        self.clear_atlas()
        layout = AtlasLayout.calculate(panorama.level.width, panorama.level.height, memory_mib,
                                       int(GL.glGetIntegerv(GL.GL_MAX_TEXTURE_SIZE)),
                                       int(GL.glGetIntegerv(GL.GL_MAX_ARRAY_TEXTURE_LAYERS)))
        self.atlas = TextureAtlas(layout)
        return layout

    def clear_atlas(self):
        if self.atlas is not None:
            self.atlas.close()
            self.atlas = None

    def close(self):
        self.clear_atlas()
        self.program.close()
        if self.vertex_array is not None:
            GL.glDeleteVertexArrays(1, [self.vertex_array])
            self.vertex_array = None

    @staticmethod
    def clear():
        GL.glClearColor(.065, .086, .114, 1)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

    def render(self, panorama, camera, sky=None):
        self.clear()
        if self.atlas is None:
            return False
        _, _, width, height = GL.glGetIntegerv(GL.GL_VIEWPORT)
        if width <= 0 or height <= 0:
            return False
        self._draw(panorama, camera, int(width), int(height), sky)
        return True

    def _draw(self, panorama, camera, width, height, sky):
        self._bind_pipeline()
        self.atlas.bind(self.program)
        self._image_uniforms(width, height)
        self._camera_uniforms(camera)
        self._projection_uniforms(panorama)
        SkyUniforms.bind(self.program, sky)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)

    def _bind_pipeline(self):
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glUseProgram(self.program.handle)
        GL.glBindVertexArray(self.vertex_array)

    def _image_uniforms(self, width, height):
        layout = self.atlas.layout
        self.program.float_pair('viewportSize', width, height)
        self.program.integer_pair('imageSize', layout.width, layout.height)
        self.program.integer('pageSize', layout.side)
        self.program.integer('pageColumns', layout.columns)

    def _camera_uniforms(self, camera):
        names = ('cameraRight', 'cameraUp', 'cameraForward')
        for name, vector in zip(names, SphericalProjection.camera_basis(camera.yaw, camera.pitch)):
            self.program.vector(name, vector)
        self.program.scalar('tanHalfFov', math.tan(math.radians(camera.fov) / 2))

    def _projection_uniforms(self, panorama):
        self.program.scalar('azimuthOrigin', panorama.azimuth_origin)
        self.program.scalar('topLatitude', panorama.top)
        self.program.scalar('latitudeSpan', panorama.span)

    @staticmethod
    def save_snapshot(path):
        _, _, width, height = GL.glGetIntegerv(GL.GL_VIEWPORT)
        GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
        pixels = GL.glReadPixels(0, 0, int(width), int(height), GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
        image = Image.frombytes('RGB', (int(width), int(height)), pixels)
        image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(path, format='PNG')
