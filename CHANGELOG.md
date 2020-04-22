# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [Unreleased]
###
- Adapt to Node API changes in pytest-5.4 (Fixes #11)
- Add support for python 3.8 (Fixes #15)
- Add support for skipif option in testoutput directive (Fixes #17)
- Add support for skipif option in testcode directive (Fixes #21)
- A ValueError is raised if the text inside the directives is not properly
  formatted.
- Ignore the option :hide: in directives (Fixes #19)

## [0.2.2] - 2019-05-24
###
- Add hack for handling mock style objects
- Add support for indented directives (Fixes #6)

## [0.2.1] - 2018-09-09
###
- Support sorting of doctests (Fixes #1)

## [0.2] - 2017-11-10
###
- Support for optionflags in `.. testoutput::`
- Optionflags from `pytest.ini` are used as the default options

## [0.1.2] - 2017-11-04
### Added
- This CHANGELOG file.

[Unreleased]: https://github.com/olivierlacan/keep-a-changelog/compare/v0.1.2...HEAD
