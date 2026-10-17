# Security policy

## Supported versions

Security fixes go into the latest release only. The installers always install
the latest release, so running the install command again updates you.

## Reporting a vulnerability

Please report security problems privately through
[GitHub's private vulnerability reporting](https://github.com/oumarknt31/xeroform-slicer/security/advisories/new)
rather than in a public issue. Include the XeroForm version (Help ▸ About), your
operating system, and the steps or file that trigger the problem.

You can expect a first reply within a week.

## How releases are protected

- Release builds run only on GitHub Actions from tagged commits; every action is
  pinned to a commit hash.
- Each release publishes `SHA256SUMS.txt`, and the install scripts refuse a
  download whose checksum doesn't match.
- The app doesn't open files referenced from inside a model (such as OBJ
  materials) and refuses project files that point to network locations.
