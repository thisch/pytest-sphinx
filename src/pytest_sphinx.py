"""
http://www.sphinx-doc.org/en/stable/ext/doctest.html
https://github.com/sphinx-doc/sphinx/blob/master/sphinx/ext/doctest.py

* TODO
** CLEANUP: use the sphinx directive parser from the sphinx project
"""
import doctest
import enum
import re
import sys
import textwrap
import traceback
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

import _pytest.doctest
import pytest
from _pytest.config import Config
from _pytest.doctest import DoctestItem
from _pytest.doctest import _is_mocked
from _pytest.doctest import _patch_unwrap_mock_aware
from _pytest.main import Session
from _pytest.pathlib import import_path
from _pytest.python import Package

if TYPE_CHECKING:
    import io
    import pdb
    from doctest import _Out

    _SpoofOut = io.StringIO


class SphinxDoctestDirectives(enum.Enum):
    TESTCODE = 1
    TESTOUTPUT = 2
    TESTSETUP = 3
    TESTCLEANUP = 4
    DOCTEST = 5


_DIRECTIVES_W_OPTIONS = (
    SphinxDoctestDirectives.TESTOUTPUT,
    SphinxDoctestDirectives.DOCTEST,
)
_DIRECTIVES_W_SKIPIF = (
    SphinxDoctestDirectives.TESTCODE,
    SphinxDoctestDirectives.TESTOUTPUT,
    SphinxDoctestDirectives.TESTSETUP,
    SphinxDoctestDirectives.TESTCLEANUP,
    SphinxDoctestDirectives.DOCTEST,
)


def pytest_collect_file(
    file_path: Path, parent: Union[Session, Package]
) -> Optional[Union["SphinxDoctestModule", "SphinxDoctestTextfile"]]:
    config = parent.config
    if file_path.suffix == ".py":
        if config.option.doctestmodules:
            mod: Union[
                "SphinxDoctestModule", "SphinxDoctestTextfile"
            ] = SphinxDoctestModule.from_parent(parent, path=file_path)
            return mod
    elif _is_doctest(config, file_path, parent):
        return SphinxDoctestTextfile.from_parent(parent, path=file_path)  # type: ignore
    return None


GlobDict = Dict[str, Any]


def _is_doctest(config: Config, path: Path, parent: Union[Session, Package]) -> bool:
    if path.suffix in (".txt", ".rst", ".md") and parent.session.isinitpath(path):
        return True
    globs = config.getoption("doctestglob") or ["test*.txt"]
    assert isinstance(globs, list)
    for glob in globs:
        if path.match(path_pattern=glob):
            return True
    return False


# This regular expression looks for option directives in the expected output
# (testoutput) code of an example.  Option directives are comments starting
# with ":options:".
_OPTION_DIRECTIVE_RE = re.compile(r':options:\s*([^\n\'"]*)$')
_OPTION_SKIPIF_RE = re.compile(r':skipif:\s*([^\n\'"]*)$')

_DIRECTIVE_RE = re.compile(
    r"""
    (?P<myst_directive>`{3}{eval-rst}\n?)?
    \s*\.\.\s
    (?P<directive>(testcode|testoutput|testsetup|testcleanup|doctest))
    ::\s*
    (?P<argument>([^\n'"]*))
    $
    """,
    re.VERBOSE,
)


def _split_into_body_and_options(
    section_content: str,
) -> Tuple[str, Optional[str], Dict[int, bool]]:
    """Parse the the full content of a directive and split it.

    It is split into a string, where the options (:options:, :hide: and
    :skipif:) are removed, and into options.

    If there are options in `section_content`, they have to appear at the
    very beginning. The first line that is not an option (:options:, :hide:
    and :skipif:) and not a newline is the first line of the string that is
    returned (`remaining`).

    Parameters
    ----------
    section_content : str
        String consisting of optional options (:skipif:, :hide:
        or :options:), and of a body.

    Returns
    -------
    body : str
    skipif_expr : str or None
    flag_settings : dict

    Raises
    ------
    ValueError
        * If options and the body of the section are not
        separated by a newline.
        * If the body of the section is empty.

    """
    lines = section_content.strip().splitlines()

    skipif_expr = None
    flag_settings = {}
    i = 0
    for line in lines:
        stripped = line.strip()
        if _OPTION_SKIPIF_RE.match(stripped):
            skipif_match = _OPTION_SKIPIF_RE.match(stripped)
            assert skipif_match is not None
            skipif_expr = skipif_match.group(1)
            i += 1
        elif _OPTION_DIRECTIVE_RE.match(stripped):
            directive_match = _OPTION_DIRECTIVE_RE.match(stripped)
            assert directive_match is not None
            option_strings = directive_match.group(1).replace(",", " ").split()
            for option in option_strings:
                if (
                    option[0] not in "+-"
                    or option[1:] not in doctest.OPTIONFLAGS_BY_NAME
                ):
                    raise ValueError(f"doctest has an invalid option {option}")
                flag = doctest.OPTIONFLAGS_BY_NAME[option[1:]]
                flag_settings[flag] = option[0] == "+"
            i += 1
        elif stripped == ":hide:":
            i += 1
        else:
            break

    if i == len(lines):
        raise ValueError("no code/output")

    body = "\n".join(lines[i:]).lstrip()
    if not body:
        raise ValueError("no code/output")

    if i and lines[i].strip():
        # no newline between option block and body
        raise ValueError(f"invalid option block: {section_content!r}")

    return body, skipif_expr, flag_settings


def _get_next_textoutputsections(
    sections: List["Section"], index: int
) -> Iterator["Section"]:
    """Yield successive TESTOUTPUT sections."""
    for j in range(index, len(sections)):
        section = sections[j]
        if section.directive == SphinxDoctestDirectives.TESTOUTPUT:
            yield section
        else:
            break


SectionGroups = Optional[List[str]]


class Section:
    def __init__(
        self,
        directive: SphinxDoctestDirectives,
        content: str,
        lineno: int,
        groups: SectionGroups = None,
    ) -> None:
        super().__init__()
        self.directive = directive
        self.groups = groups
        self.lineno = lineno
        body, skipif_expr, options = _split_into_body_and_options(content)

        if skipif_expr and self.directive not in _DIRECTIVES_W_SKIPIF:
            raise ValueError(f":skipif: not allowed in {self.directive}")
        if options and self.directive not in _DIRECTIVES_W_OPTIONS:
            raise ValueError(f":options: not allowed in {self.directive}")
        self.body = body
        self.skipif_expr = skipif_expr
        self.options = options


def get_sections(docstring: str) -> List[Union[Any, Section]]:
    lines = textwrap.dedent(docstring).splitlines()
    sections = []

    def _get_indentation(line: str) -> int:
        return len(line) - len(line.lstrip())

    def add_match(
        directive: SphinxDoctestDirectives, i: int, j: int, groups: SectionGroups
    ) -> None:
        sections.append(
            Section(
                directive,
                textwrap.dedent("\n".join(lines[i + 1 : j])),
                lineno=j - 1,
                groups=groups,
            )
        )

    i = 0
    while True:
        try:
            line = lines[i]
        except IndexError:
            break

        match = _DIRECTIVE_RE.match(line)
        if match:
            group = match.groupdict()
            directive = getattr(SphinxDoctestDirectives, group["directive"].upper())
            groups = [x.strip() for x in (group["argument"] or "default").split(",")]
            indentation = _get_indentation(line)
            # find the end of the block
            j = i
            while True:
                j += 1
                try:
                    block_line = lines[j]
                except IndexError:
                    add_match(directive, i, j, groups)
                    break
                if block_line.lstrip() and _get_indentation(block_line) <= indentation:
                    add_match(directive, i, j, groups)
                    i = j - 1
                    break
        i += 1
    return sections


def docstring2examples(
    docstring: str, globs: Optional[GlobDict] = None
) -> List[Union[Any, doctest.Example]]:
    """
    Parse all sphinx test directives in the docstring and create a
    list of examples.
    """
    # TODO subclass doctest.DocTestParser instead?

    if globs is None:
        globs = {}

    sections = get_sections(docstring)

    def get_testoutput_section_data(
        section: "Section",
    ) -> Tuple[str, Dict[int, bool], int, Optional[Any]]:
        want = section.body
        exc_msg = None
        options: Dict[int, bool] = {}

        if section.skipif_expr and eval(section.skipif_expr, globs):
            want = ""
        else:
            options = section.options
            match = doctest.DocTestParser._EXCEPTION_RE.match(want)  # type: ignore
            if match:
                exc_msg = match.group("msg")

        return want, options, section.lineno, exc_msg

    examples = []
    for i, current_section in enumerate(sections):
        # TODO support SphinxDoctestDirectives.TESTSETUP, ...
        if current_section.directive == SphinxDoctestDirectives.TESTCODE:
            next_testoutput_sections = _get_next_textoutputsections(sections, i + 1)
            section_data_seq = [
                get_testoutput_section_data(s) for s in next_testoutput_sections
            ]

            num_unskipped_sections = len([d for d in section_data_seq if d[0]])
            if num_unskipped_sections > 1:
                raise ValueError("There are multiple unskipped TESTOUTPUT sections")

            if num_unskipped_sections:
                want, options, _, exc_msg = next(d for d in section_data_seq if d[0])
            else:
                # no unskipped testoutput section
                # do we really need doctest.Example to test
                # independent TESTCODE sections?
                want, options, exc_msg = "", {}, None

            if current_section.skipif_expr and eval(current_section.skipif_expr, globs):
                # TODO add the doctest.Example to `examples` but mark it as
                # skipped.
                continue

            examples.append(
                doctest.Example(
                    source=current_section.body,
                    want=want,
                    exc_msg=exc_msg,
                    # we want to see the ..testcode lines in the
                    # console output but not the ..testoutput
                    # lines
                    # TODO why do we want to hide testoutput??
                    lineno=current_section.lineno,
                    options=options,
                )
            )
    return examples


class SphinxDocTestRunner(doctest.DebugRunner):
    """
    overwrite doctest.DocTestRunner.__run, since it uses 'single' for the
    `compile` function instead of 'exec'.
    """

    _checker: "doctest.OutputChecker"
    _fakeout: "_SpoofOut"
    debugger: "pdb.Pdb"

    def _DocTestRunner__run(
        self, test: doctest.DocTest, compileflags: int, out: "_Out"
    ) -> doctest.TestResults:
        """
        Run the examples in `test`.

        Write the outcome of each example with one of the
        `DocTestRunner.report_*` methods, using the writer function
        `out`.  `compileflags` is the set of compiler flags that should
        be used to execute examples.  Return a tuple `(f, t)`, where `t`
        is the number of examples tried, and `f` is the number of
        examples that failed.  The examples are run in the namespace
        `test.globs`.

        """
        # Keep track of the number of failures and tries.
        failures = tries = 0

        # Save the option flags (since option directives can be used
        # to modify them).
        original_optionflags = self.optionflags

        SUCCESS, FAILURE, BOOM = range(3)  # `outcome` state

        check = self._checker.check_output

        # Process each example.
        for examplenum, example in enumerate(test.examples):

            # If REPORT_ONLY_FIRST_FAILURE is set, then suppress
            # reporting after the first failure.
            quiet = (
                self.optionflags & doctest.REPORT_ONLY_FIRST_FAILURE and failures > 0
            )

            # Merge in the example's options.
            self.optionflags = original_optionflags
            if example.options:
                for (optionflag, val) in example.options.items():
                    if val:
                        self.optionflags |= optionflag
                    else:
                        self.optionflags &= ~optionflag

            # If 'SKIP' is set, then skip this example.
            if self.optionflags & doctest.SKIP:
                continue

            # Record that we started this example.
            tries += 1
            if not quiet:
                self.report_start(out, test, example)

            # Use a special filename for compile(), so we can retrieve
            # the source code during interactive debugging (see
            # __patched_linecache_getlines).
            filename = "<doctest %s[%d]>" % (test.name, examplenum)

            # Run the example in the given context (globs), and record
            # any exception that gets raised.  (But don't intercept
            # keyboard interrupts.)
            try:
                # Don't blink!  This is where the user's code gets run.
                exec(
                    compile(example.source, filename, "exec", compileflags, 1),
                    test.globs,
                )
                self.debugger.set_continue()  # ==== Example Finished ====
                exception = None
            except KeyboardInterrupt:
                raise
            except Exception:
                exception = sys.exc_info()
                self.debugger.set_continue()  # ==== Example Finished ====

            got = self._fakeout.getvalue()  # the actual output
            self._fakeout.truncate(0)
            outcome = FAILURE  # guilty until proved innocent or insane

            # If the example executed without raising any exceptions,
            # verify its output.
            if exception is None:
                if check(example.want, got, self.optionflags):
                    outcome = SUCCESS

            # The example raised an exception:  check if it was expected.
            else:
                exc_msg = traceback.format_exception_only(*exception[:2])[-1]
                if not quiet:
                    got += doctest._exception_traceback(exception)  # type:ignore

                # If `example.exc_msg` is None, then we weren't expecting
                # an exception.
                if example.exc_msg is None:
                    outcome = BOOM

                # We expected an exception:  see whether it matches.
                elif check(example.exc_msg, exc_msg, self.optionflags):
                    outcome = SUCCESS

                # Another chance if they didn't care about the detail.
                elif self.optionflags & doctest.IGNORE_EXCEPTION_DETAIL:
                    if check(
                        doctest._strip_exception_details(  # type:ignore
                            example.exc_msg,
                        ),
                        doctest._strip_exception_details(exc_msg),  # type:ignore
                        self.optionflags,
                    ):
                        outcome = SUCCESS

            # Report the outcome.
            if outcome is SUCCESS:
                if not quiet:
                    self.report_success(out, test, example, got)
            elif outcome is FAILURE:
                if not quiet:
                    self.report_failure(out, test, example, got)
                failures += 1
            elif outcome is BOOM:
                if not quiet:
                    assert exception is not None
                    assert out is not None
                    self.report_unexpected_exception(
                        out,
                        test,
                        example,
                        exception,  # type:ignore
                    )
                failures += 1
            else:
                assert False, ("unknown outcome", outcome)

            if failures and self.optionflags & doctest.FAIL_FAST:
                break

        # Restore the option flags (in case they were modified)
        self.optionflags = original_optionflags

        # Record and return the number of failures and tries.
        self._DocTestRunner__record_outcome(test, failures, tries)  # type:ignore
        return doctest.TestResults(failures, tries)


class SphinxDocTestParser:
    def get_doctest(
        self,
        docstring: str,
        globs: Dict[str, Any],
        name: str,
        filename: str,
        lineno: int,
    ) -> doctest.DocTest:
        # TODO document why we need to overwrite? get_doctest
        return doctest.DocTest(
            examples=docstring2examples(docstring, globs=globs),
            globs=globs,
            name=name,
            filename=filename,
            lineno=lineno,
            docstring=docstring,
        )


class SphinxDoctestTextfile(pytest.Module):
    obj = None

    def collect(self) -> Iterator[_pytest.doctest.DoctestItem]:
        # inspired by doctest.testfile; ideally we would use it directly,
        # but it doesn't support passing a custom checker
        encoding = self.config.getini("doctest_encoding")
        text = self.fspath.read_text(encoding)
        name = self.fspath.basename

        optionflags = _pytest.doctest.get_optionflags(self)  # type:ignore
        runner = SphinxDocTestRunner(
            verbose=False,
            optionflags=optionflags,
            checker=_pytest.doctest._get_checker(),
        )

        test = doctest.DocTest(
            examples=docstring2examples(text),
            globs={},
            name=name,
            filename=name,
            lineno=0,
            docstring=text,
        )

        if test.examples:
            yield DoctestItem.from_parent(
                parent=self,  # type:ignore
                name=test.name,
                runner=runner,
                dtest=test,
            )


class SphinxDoctestModule(pytest.Module):
    def collect(self) -> Iterator[_pytest.doctest.DoctestItem]:
        if self.fspath.basename == "conftest.py":
            module = self.config.pluginmanager._importconftest(
                self.path,
                self.config.getoption("importmode"),
                rootpath=self.config.rootpath,
            )
        else:
            try:
                module = import_path(self.path, root=self.config.rootpath)
            except ImportError:
                if self.config.getvalue("doctest_ignore_import_errors"):
                    pytest.skip("unable to import module %r" % self.path)
                else:
                    raise
        optionflags = _pytest.doctest.get_optionflags(self)  # type:ignore

        class MockAwareDocTestFinder(doctest.DocTestFinder):
            """
            a hackish doctest finder that overrides stdlib internals to fix
            a stdlib bug
            https://github.com/pytest-dev/pytest/issues/3456
            https://bugs.python.org/issue25532

            fix taken from https://github.com/pytest-dev/pytest/pull/4212/
            """

            def _find(
                self,
                tests: List[doctest.DocTest],
                obj: str,
                name: str,
                module: Any,
                source_lines: Optional[List[str]],
                globs: GlobDict,
                seen: Dict[int, int],
            ) -> None:
                if _is_mocked(obj):
                    return
                with _patch_unwrap_mock_aware():
                    doctest.DocTestFinder._find(  # type:ignore
                        self,
                        tests,
                        obj,
                        name,
                        module,
                        source_lines,
                        globs,
                        seen,
                    )

        if sys.version_info < (3, 10):
            finder = MockAwareDocTestFinder(
                parser=SphinxDocTestParser()  # type:ignore
            )
        else:
            finder = doctest.DocTestFinder(parser=SphinxDocTestParser())  # type:ignore

        runner = SphinxDocTestRunner(
            verbose=False,
            optionflags=optionflags,
            checker=_pytest.doctest._get_checker(),
        )

        for test in finder.find(module, module.__name__):
            if test.examples:
                yield DoctestItem.from_parent(
                    parent=self,  # type: ignore
                    name=test.name,
                    runner=runner,
                    dtest=test,
                )
