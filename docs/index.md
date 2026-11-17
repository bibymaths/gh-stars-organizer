# Documentation index

This is the deterministic version of GitHub Stars Organizer. Read [the README](../README.md) for the quickstart and conservative mutation policy.

- [Installation and full CLI reference](cli.md)
- [Configuration, profiles, overrides and classifications](configuration.md)
- [Safety, Star Lists and recovery](safety.md)
- [Architecture and local caching](architecture.md)
- [Testing, CI and current validation status](testing.md)
- [Troubleshooting and FAQ](troubleshooting.md)

The GitHub Lists GraphQL mutations `createUserList` and `updateUserListsForItem` exist in GitHub's published schema, but the implementation has not run a real mutation through this session. Review plan backups carefully before any first application.
