#!/usr/bin/env python3
"""Enforce the objective Python structure requirements from AGENTS.md."""
import ast
from pathlib import Path
import unittest


class PythonSources:
    ROOT = Path(__file__).resolve().parents[1]
    DIRECTORIES = ('panorama_viewer', 'panorama_archive', 'monitoring-server', 'tests')

    @classmethod
    def paths(cls):
        files = list(cls.ROOT.glob('*.py'))
        for directory in cls.DIRECTORIES:
            files.extend((cls.ROOT / directory).rglob('*.py'))
        return sorted(files)

    @classmethod
    def methods(cls):
        for path in cls.paths():
            tree = ast.parse(path.read_text())
            parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield path, node, parents[node]


class ArchitectureTests(unittest.TestCase):
    def test_python_files_begin_with_required_shebang(self):
        for path in PythonSources.paths():
            with self.subTest(path=path.relative_to(PythonSources.ROOT)):
                self.assertTrue(path.read_text().startswith('#!/usr/bin/env python3\n'))

    def test_all_functions_are_methods_of_classes(self):
        for path, method, parent in PythonSources.methods():
            with self.subTest(path=path.name, method=method.name):
                self.assertIsInstance(parent, ast.ClassDef)

    def test_methods_do_not_exceed_ten_physical_lines(self):
        for path, method, _ in PythonSources.methods():
            with self.subTest(path=path.name, method=method.name):
                self.assertLessEqual(method.end_lineno - method.lineno + 1, 10)

    def test_runtime_dependencies_are_in_shared_requirements(self):
        content = (PythonSources.ROOT / 'requirements.txt').read_text().lower()
        for dependency in ('pillow', 'requests', 'numpy', 'flask', 'psycopg', 'flask-cors', 'pyopengl', 'pygobject'):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, content)


if __name__ == '__main__':
    unittest.main()
