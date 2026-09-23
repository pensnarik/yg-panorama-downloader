#!/usr/bin/env python3
"""GLSL programs for exact spherical sampling."""

class ShaderSources:
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
