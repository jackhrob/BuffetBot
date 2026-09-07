# Local runtime directories

The example configurations use `var/state`, `var/data`, and `var/artifacts`.
Their contents are ignored by Git. This README is the only tracked file here.

`buffetbot doctor` inspects these paths without creating directories or writing
files. Missing directories are acceptable when their nearest existing parent is
writable and searchable. Future commands that produce state will create their
own directories after validating configuration.

Keep source files and secrets out of these directories. Put local credentials in
the explicitly selected `config/secrets.local.toml` file or the documented
environment variables. Custom runtime paths must be non-overlapping and either
under a project's `var/` directory or outside its project tree.
