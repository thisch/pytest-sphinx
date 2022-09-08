# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [Unreleased]
###

## [0.5.0] - 2022-09-06
###
 - Mention in the README that the doctest directive is supported.
 - internal: Improve CI setup, from [Tony
   Narlock](https://www.git-pull.com).
 - internal: Switch to a src/ structure, from [Tony
   Narlock](https://www.git-pull.com).
 - internal: Switch from setup.py to a PEP-621 pyproject.toml, from
   [Tony Narlock](https://www.git-pull.com).

- Support for markdown `.md` files and `{eval-rst}` myst-parser directives, from 
  [Tony Narlock](https://www.git-pull.com) (re: #30, via #31).

## [0.4.0] - 2022-03-30
###
 - Drop python2.7 (Fixes #14)
 - Drop python3.5 and python3.6
 - Require pytest>=7.0

## [0.3.1] - 2020-08-05
###
- Adapt to importmode API changes in pytest-6.0

## [0.3] - 2020-08-04
###
- Adapt to Node API changes in pytest-5.4 (Fixes #11)
- Add support for python 3.8 (Fixes #15)
- Add support for skipif option in testoutput directive (Fixes #17)
- Add support for skipif option in testcode directive (Fixes #21)
- A ValueError is raised if the text inside the directives is not properly
  formatted.
- Ignore the option :hide: in directives (Fixes #19)
- Fix detection of block boundaries in parser.

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
