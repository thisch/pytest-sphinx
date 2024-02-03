""" Run tests that call "sphinx-build -M doctest". """

import logging
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Iterator
from typing import Union

import pytest
from _pytest._py.path import LocalPath
from _pytest.legacypath import Testdir

logger = logging.getLogger(__name__)


class SphinxDoctestRunner:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path: Path = tmp_path
        subprocess.check_output(
            [
                "sphinx-quickstart",
                "-v",
                "0.1",
                "-r",
                "0.1",
                "-l",
                "en",
                "-a",
                "my.name",
                "--ext-doctest",  # enable doctest extension
                "--sep",
                "-p",
                "demo",
                ".",
            ]
        )

    def __call__(
        self, rst_file_content: str, must_raise: bool = False, sphinxopts: None = None
    ) -> str:
        index_rst = self.tmp_path / "source" / "index.rst"
        rst_file_content = textwrap.dedent(rst_file_content)
        index_rst.write_text(rst_file_content, encoding="utf-8")
        logger.info("CWD: %s", os.getcwd())
        logger.info("content of index.rst:\n%s", rst_file_content)

        cmd = ["sphinx-build", "-M", "doctest", "source", ""]
        if sphinxopts:
            cmd.append(sphinxopts)

        def to_str(subprocess_output: Union[str, bytes]) -> str:
            if isinstance(subprocess_output, bytes):
                output_str = "\n".join(subprocess_output.decode().splitlines())
            else:
                output_str = subprocess_output
            logger.info("%s produced:\n%s", cmd, output_str)
            return output_str

        if must_raise:
            with pytest.raises(subprocess.CalledProcessError) as excinfo:
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return to_str(excinfo.value.output)
        return to_str(subprocess.check_output(cmd))


@pytest.fixture
def sphinx_tester(tmpdir: LocalPath) -> Iterator[SphinxDoctestRunner]:
    with tmpdir.as_cwd():
        yield SphinxDoctestRunner(tmpdir)


def test_simple_doctest_failure(sphinx_tester: SphinxDoctestRunner) -> None:

    output = sphinx_tester(
        """
        ===!!!

        >>> 3 + 3
        5
        """,
        must_raise=True,
    )

    expected = textwrap.dedent(
        """
    Failed example:
        3 + 3
    Expected:
        5
    Got:
        6
    """
    )

    assert expected in output, f"{expected!r}\n\n{output!r}"


def test_simple_doctest_success(sphinx_tester: SphinxDoctestRunner) -> None:
    output = sphinx_tester(
        """
        ===!!!

        >>> 3 + 3
        6
        """
    )
    assert "1 items passed all tests" in output


class TestDirectives:
    def test_testcode(
        self, testdir: Testdir, sphinx_tester: SphinxDoctestRunner
    ) -> None:
        code = """
            .. testcode::

                print("msg from testcode directive")

            .. testoutput::

                msg from testcode directive
            """

        sphinx_output = sphinx_tester(code)
        assert "1 items passed all tests" in sphinx_output

        plugin_result = testdir.runpytest("--doctest-glob=index.rst").stdout
        plugin_result.fnmatch_lines(["*=== 1 passed in *"])

    def test_doctest(
        self, testdir: Testdir, sphinx_tester: SphinxDoctestRunner
    ) -> None:
        code = """
            .. doctest::

               >>> print("msg from testcode directive")
               msg from testcode directive
            """

        sphinx_output = sphinx_tester(code)
        assert "1 items passed all tests" in sphinx_output

        plugin_result = testdir.runpytest("--doctest-glob=index.rst").stdout
        plugin_result.fnmatch_lines(["*=== 1 passed in *"])

    def test_doctest_multiple(
        self, testdir: Testdir, sphinx_tester: SphinxDoctestRunner
    ) -> None:
        code = """
            .. doctest::

                >>> import operator

                >>> operator.lt(1, 3)
                True

                >>> operator.lt(6, 2)
                False

            .. doctest::

                >>> four = 2 + 2

                >>> four
                4

                >>> print(f'Two plus two: {four}')
                Two plus two: 4
            """

        sphinx_output = sphinx_tester(code)
        assert "1 items passed all tests" in sphinx_output

        plugin_result = testdir.runpytest("--doctest-glob=index.rst").stdout
        plugin_result.fnmatch_lines(["*=== 1 passed in *"])

    @pytest.mark.parametrize("testcode", ["raise RuntimeError", "pass", "print(1234)"])
    def test_skipif_true(
        self, testdir: Testdir, sphinx_tester: SphinxDoctestRunner, testcode: str
    ) -> None:
        code = """
            .. testcode::

                {}

            .. testoutput::
                :skipif: True

                NOT EVALUATED
            """.format(
            testcode
        )

        raise_in_testcode = testcode != "pass"
        sphinx_output = sphinx_tester(code, must_raise=raise_in_testcode)

        # -> ignore the testoutput section if skipif evaluates to True, but
        # -> always run the code in testcode
        plugin_output = testdir.runpytest("--doctest-glob=index.rst").stdout

        if raise_in_testcode:
            assert "1 failure in tests" in sphinx_output
            plugin_output.fnmatch_lines(["*=== 1 failed in *"])
        else:
            assert "1 items passed all tests" in sphinx_output
            plugin_output.fnmatch_lines(["*=== 1 passed in *"])

    @pytest.mark.parametrize(
        "testcode", ["raise RuntimeError", "pass", "print('EVALUATED')"]
    )
    def test_skipif_false(
        self, testdir: Testdir, sphinx_tester: SphinxDoctestRunner, testcode: str
    ) -> None:
        code = """
            .. testcode::

                {}

            .. testoutput::
                :skipif: False

                EVALUATED
            """.format(
            testcode
        )

        expected_failure = "EVALUATED" not in testcode

        sphinx_output = sphinx_tester(code, must_raise=expected_failure)
        plugin_output = testdir.runpytest("--doctest-glob=index.rst").stdout

        if expected_failure:
            assert "1 failure in tests" in sphinx_output
            plugin_output.fnmatch_lines(["*=== 1 failed in *"])
        else:
            assert "1 items passed all tests" in sphinx_output
            plugin_output.fnmatch_lines(["*=== 1 passed in *"])

    @pytest.mark.parametrize("wrong_output_assertion", [True, False])
    def test_skipif_multiple_testoutput(
        self,
        testdir: Testdir,
        sphinx_tester: SphinxDoctestRunner,
        wrong_output_assertion: bool,
    ) -> None:
        # TODO add test, where there are muliple un-skipped testoutput
        # sections. IMO this must lead to a testfailure, which is currently
        # not the case in sphinx -> Create sphinx ticket
        code = """
            .. testcode::

                raise RuntimeError

            .. testoutput::
                :skipif: True

                NOT EVALUATED

            .. testoutput::
                :skipif: False

                Traceback (most recent call last):
                    ...
                {}
            """.format(
            "ValueError" if wrong_output_assertion else "RuntimeError"
        )

        # -> ignore all skipped testoutput sections, but use the one that is
        # -> not skipped

        sphinx_output = sphinx_tester(code, must_raise=wrong_output_assertion)

        plugin_output = testdir.runpytest("--doctest-glob=index.rst").stdout

        if wrong_output_assertion:
            assert "1 failure in tests" in sphinx_output
            plugin_output.fnmatch_lines(["*=== 1 failed in *"])
        else:
            assert "1 items passed all tests" in sphinx_output
            plugin_output.fnmatch_lines(["*=== 1 passed in *"])

    @pytest.mark.parametrize("testcode", ["raise RuntimeError", "pass", "print(1234)"])
    def test_skipif_true_in_testcode(
        self, testdir: Testdir, sphinx_tester: SphinxDoctestRunner, testcode: str
    ) -> None:
        code = """
            .. testcode::
                :skipif: True

                {}

            .. testoutput::
                :skipif: False

                NOT EVALUATED
            """.format(
            testcode
        )

        sphinx_output = sphinx_tester(code, must_raise=False)
        assert "0 tests" in sphinx_output

        plugin_output = testdir.runpytest("--doctest-glob=index.rst").stdout
        plugin_output.fnmatch_lines(["collected 0 items"])
