#!/usr/bin/env python3
"""Shared validation for browser captures and directly fetched metadata."""
from panorama_archive.capture import CaptureNormalizer, GeometryValidator

normalize_capture = CaptureNormalizer.normalize
