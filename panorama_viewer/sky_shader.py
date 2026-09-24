#!/usr/bin/env python3
"""Analytic angular discs and the altitude-zero great circle."""
import math


class SkyUniforms:
    @classmethod
    def bind(cls, program, overlay):
        enabled = overlay is not None and overlay.enabled
        program.integer('showSun', int(enabled and overlay.sun_enabled))
        program.integer('showMoon', int(enabled and overlay.moon_enabled))
        if enabled:
            cls._body(program, 'sun', overlay.snapshot.sun)
            cls._body(program, 'moon', overlay.snapshot.moon)
            program.vector('moonLight', overlay.snapshot.moon_light)

    @staticmethod
    def _body(program, prefix, body):
        program.vector(prefix + 'Direction', body.direction)
        program.scalar(prefix + 'Radius', math.sin(body.radius))


class SkyShader:
    SOURCE = '''
    uniform bool showSun, showMoon;
    uniform vec3 sunDirection, moonDirection, moonLight;
    uniform float sunRadius, moonRadius;

    vec3 disc(vec3 background, vec3 ray, vec3 center, float radius, bool moon) {
        float perpendicular = length(cross(ray, center));
        float forward = dot(ray, center);
        float edge = max(fwidth(perpendicular), 1e-8);
        float coverage = 1.0 - smoothstep(radius - edge * 0.5, radius + edge * 0.5, perpendicular);
        if (forward <= 0.0 || coverage <= 0.0) return background;
        float depth = sqrt(max(0.0, radius * radius - perpendicular * perpendicular));
        vec3 normal = normalize(ray * (forward - depth) - center);
        float illumination = max(dot(normal, moonLight), 0.0);
        vec3 moonColor = mix(vec3(0.045, 0.05, 0.06), vec3(0.9, 0.9, 0.85), sqrt(illumination));
        vec3 sunColor = vec3(1.0, 0.88, 0.48) * (0.8 + 0.2 * depth / radius);
        return mix(background, moon ? moonColor : sunColor, coverage);
    }

    vec3 skyOverlay(vec3 background, vec3 ray) {
        if (!showSun && !showMoon) return background;
        float horizonWidth = max(fwidth(ray.y), 1e-8);
        float horizon = 1.0 - smoothstep(0.2, 1.0, abs(ray.y) / horizonWidth);
        vec3 result = mix(background, vec3(0.2, 0.85, 0.95), horizon * 0.85);
        if (showSun) result = disc(result, ray, sunDirection, sunRadius, false);
        if (showMoon) result = disc(result, ray, moonDirection, moonRadius, true);
        return result;
    }
    '''
