# -*- coding: utf-8 -*-
"""
http://www.sphinx-doc.org/en/stable/ext/doctest.html
https://github.com/sphinx-doc/sphinx/blob/master/sphinx/ext/doctest.py

* TODO
** CLEANUP: use the sphinx directive parser from the sphinx project
"""

import doctest
import enum
import itertools
import re
import textwrap
import sys
import traceback

import _pytest.doctest
from _pytest.doctest import DoctestItem
import pytest


def pairwise(iterable):
    """
    s -> (s0,s1), (s1,s2), (s2, s3), ...
    """
    a, b = itertools.tee(iterable)
    next(b, None)
    return list(zip(a, b))


class SkippedOutputAssertion(Exception):
    # only used for the testoutput directive
    pass


class SphinxDoctestDirectives(enum.Enum):
    TESTCODE = 1
    TESTOUTPUT = 2
    TESTSETUP = 3
    TESTCLEANUP = 4
    DOCTEST = 5


def pytest_collect_file(path, parent):
    config = parent.config
    if path.ext == ".py":
        if config.option.doctestmodules:
            if hasattr(SphinxDoctestModule, "from_parent"):
                return SphinxDoctestModule.from_parent(parent, fspath=path)
            else:
                return SphinxDoctestModule(path, parent)
    elif _is_doctest(config, path, parent):
        if hasattr(SphinxDoctestTextfile, "from_parent"):
            return SphinxDoctestTextfile.from_parent(parent, fspath=path)
        else:
            return SphinxDoctestTextfile(path, parent)


def _is_doctest(config, path, parent):
    if path.ext in (".txt", ".rst") and parent.session.isinitpath(path):
        return True
    globs = config.getoption("doctestglob") or ["test*.txt"]
    for glob in globs:
        if path.check(fnmatch=glob):
            return True
    return False


# This regular expression looks for option directives in the expected output
# (testoutput) code of an example.  Option directives are comments starting
# with ":options:".
_OPTION_DIRECTIVE_RE = re.compile(r':options:\s*([^\n\'"]*)$')
_OPTION_SKIPIF_RE = re.compile(r':skipif:\s*([^\n\'"]*)$')


class Options:
    def __init__(self, flags, hide, skipif_expr):
        self.flags = flags
        self.hide = hide
        self.skipif_expr = skipif_expr


class Section:
    def __init__(self, name, content, lineno, group="default"):
        self.name = name
        self.group = group
        self.lineno = lineno
        content, options = _extract_options(content.strip())
        self.content = content
        self.options = options


def _extract_options(section_content):
    lines = section_content.strip().splitlines()
    # iterate over lines and remove the ones that contain options
    # once a newline is found, stop and return test of the lines (stripped)

    hide = False
    skipif_expr = None
    flag_settings = {}
    i = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _OPTION_SKIPIF_RE.match(stripped):
            skipif_expr = _OPTION_SKIPIF_RE.match(stripped).group(1)
        elif stripped == ":hide:":
            hide = True
        elif _OPTION_DIRECTIVE_RE.match(stripped):
            option_strings = (
                _OPTION_DIRECTIVE_RE.match(stripped)
                .group(1)
                .replace(",", " ")
                .split()
            )
            for option in option_strings:
                if (
                    option[0] not in "+-"
                    or option[1:] not in doctest.OPTIONFLAGS_BY_NAME
                ):
                    raise ValueError(
                        "doctest " "has an invalid option {}".format(option)
                    )
                flag = doctest.OPTIONFLAGS_BY_NAME[option[1:]]
                flag_settings[flag] = option[0] == "+"
        else:
            break

    remaining = "\n".join(lines[i:]).lstrip()
    options = Options(flags=flag_settings, skipif_expr=skipif_expr, hide=hide)
    return remaining, options


def _get_next_textoutputsections(sections, index):
    """Yield successive TESTOUTPUT sections."""
    for j in range(index, len(sections)):
        section = sections[j]
        if section.name == SphinxDoctestDirectives.TESTOUTPUT:
            yield section
        else:
            break


def docstring2examples(docstring, globs=None):
    """
    Parse all sphinx test directives in the docstring and create a
    list of examples.
    """
    # TODO subclass doctest.DocTestParser instead?

    if not globs:
        globs = {}

    lines = textwrap.dedent(docstring).splitlines()
    matches = [
        i
        for i, line in enumerate(lines)
        if any(
            line.strip().startswith(".. " + d.name.lower() + "::")
            for d in SphinxDoctestDirectives
        )
    ]
    if not matches:
        return []

    matches.append(len(lines))

    def is_empty_of_indented(line):
        return not line or line.startswith("   ")

    sections = []
    for x, y in pairwise(matches):
        section = lines[x:y]
        header = section[0]
        directive = next(
            d for d in SphinxDoctestDirectives if d.name.lower() in header
        )
        out = "\n".join(itertools.takewhile(is_empty_of_indented, section[1:]))
        sections.append(Section(directive, textwrap.dedent(out), lineno=x))

    def get_testoutput_section_data(section):
        exc_msg = None

        if section.options.skipif_expr and eval(
            section.options.skipif_expr, globs
        ):
            want = ""
        else:
            want = section.content
            match = doctest.DocTestParser._EXCEPTION_RE.match(want)
            if match:
                exc_msg = match.group("msg")

        return want, section.options.flags, section.lineno, exc_msg

    examples = []
    for i, current_section in enumerate(sections):
        # TODO support SphinxDoctestDirectives.TESTSETUP, ...
        if current_section.name == SphinxDoctestDirectives.TESTCODE:
            next_testoutput_sections = _get_next_textoutputsections(
                sections, i + 1
            )
            section_data_seq = [
                get_testoutput_section_data(s)
                for s in next_testoutput_sections
            ]

            num_unskipped_sections = len([d for d in section_data_seq if d[0]])
            if num_unskipped_sections > 1:
                raise ValueError(
                    "There are multiple unskipped TESTOUTPUT sections"
                )

            if num_unskipped_sections:
                want, options, _, exc_msg = next(
                    d for d in section_data_seq if d[0]
                )
                # see comment below (where we use lineno -1)
                lineno = section_data_seq[0][2]
            else:
                # no unskipped testoutput section
                # do we really need doctest.Example to test
                # independent TESTCODE sections?
                # TODO lineno may be wrong
                want, options, lineno, exc_msg = "", {}, 1, None

            examples.append(
                doctest.Example(
                    source=current_section.content,
                    want=want,
                    exc_msg=exc_msg,
                    # we want to see the ..testcode lines in the
                    # console output but not the ..testoutput
                    # lines
                    # TODO why do we want to hide testoutput??
                    lineno=lineno - 1,
                    options=options,
                )
            )
    return examples


class SphinxDocTestRunner(doctest.DebugRunner):
    """
    overwrite doctest.DocTestRunner.__run, since it uses 'single' for the
    `compile` function instead of 'exec'.
    """

    def _DocTestRunner__run(self, test, compileflags, out):
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
                self.optionflags & doctest.REPORT_ONLY_FIRST_FAILURE
                and failures > 0
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
                    got += doctest._exception_traceback(exception)

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
                        doctest._strip_exception_details(example.exc_msg),
                        doctest._strip_exception_details(exc_msg),
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
                    self.report_unexpected_exception(
                        out, test, example, exception
                    )
                failures += 1
            else:
                assert False, ("unknown outcome", outcome)

            if failures and self.optionflags & doctest.FAIL_FAST:
                break

        # Restore the option flags (in case they were modified)
        self.optionflags = original_optionflags

        # Record and return the number of failures and tries.
        self._DocTestRunner__record_outcome(test, failures, tries)
        return doctest.TestResults(failures, tries)


class SphinxDocTestParser(object):
    def get_doctest(self, docstring, globs, name, filename, lineno):
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

    def collect(self):
        # inspired by doctest.testfile; ideally we would use it directly,
        # but it doesn't support passing a custom checker
        encoding = self.config.getini("doctest_encoding")
        text = self.fspath.read_text(encoding)
        name = self.fspath.basename

        optionflags = _pytest.doctest.get_optionflags(self)
        runner = SphinxDocTestRunner(
            verbose=0,
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
            if hasattr(DoctestItem, "from_parent"):
                yield DoctestItem.from_parent(
                    parent=self, name=test.name, runner=runner, dtest=test
                )
            else:
                yield DoctestItem(test.name, self, runner, test)


class SphinxDoctestModule(pytest.Module):
    def collect(self):
        if self.fspath.basename == "conftest.py":
            module = self.config.pluginmanager._importconftest(self.fspath)
        else:
            try:
                module = self.fspath.pyimport()
            except ImportError:
                if self.config.getvalue("doctest_ignore_import_errors"):
                    pytest.skip("unable to import module %r" % self.fspath)
                else:
                    raise
        optionflags = _pytest.doctest.get_optionflags(self)

        class MockAwareDocTestFinder(doctest.DocTestFinder):
            """
            a hackish doctest finder that overrides stdlib internals to fix
            a stdlib bug
            https://github.com/pytest-dev/pytest/issues/3456
            https://bugs.python.org/issue25532

            fix taken from https://github.com/pytest-dev/pytest/pull/4212/
            """

            def _find(
                self, tests, obj, name, module, source_lines, globs, seen
            ):
                if _is_mocked(obj):
                    return
                with _patch_unwrap_mock_aware():
                    doctest.DocTestFinder._find(
                        self,
                        tests,
                        obj,
                        name,
                        module,
                        source_lines,
                        globs,
                        seen,
                    )

        try:
            from _pytest.doctest import _is_mocked
            from _pytest.doctest import _patch_unwrap_mock_aware
        except ImportError:
            finder = doctest.DocTestFinder(parser=SphinxDocTestParser())
        else:
            finder = MockAwareDocTestFinder(parser=SphinxDocTestParser())

        runner = SphinxDocTestRunner(
            verbose=0,
            optionflags=optionflags,
            checker=_pytest.doctest._get_checker(),
        )

        for test in finder.find(module, module.__name__):
            if test.examples:
                if hasattr(DoctestItem, "from_parent"):
                    yield DoctestItem.from_parent(
                        parent=self, name=test.name, runner=runner, dtest=test
                    )
                else:
                    yield DoctestItem(test.name, self, runner, test)
