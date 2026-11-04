# File collection and discovery

You can directly pass _Black_ files, but you can also pass directories and _Black_ will
walk them, collecting files to format. It determines what files to format or skip
automatically using the inclusion and exclusion regexes and as well their modification
time.

## Ignoring unmodified files

_Black_ remembers files it has already formatted, unless code is passed via standard
input or the `--no-cache` flag is used. This information is stored per-user. The exact
location of the file depends on the _Black_ version and the system on which _Black_ is
run. The file is non-portable. The standard location on common operating systems is:

- Windows:
  `C:\Users\<username>\AppData\Local\black\black\Cache\<version>\cache.<mode-key>.pickle`
- macOS: `/Users/<username>/Library/Caches/black/<version>/cache.<mode-key>.pickle`
- Linux: `/home/<username>/.cache/black/<version>/cache.<mode-key>.pickle`

`mode-key` identifies the formatting options used for the cached files. Formatting with
different options uses a different cache file.

To override the location of these files on all systems, pass `--cache-dir` or set the
environment variable `BLACK_CACHE_DIR` to the preferred location. Alternatively on macOS
and Linux, set `XDG_CACHE_HOME` to your preferred location. For example, if you want to
put the cache in the directory you're running _Black_ from, pass
`--cache-dir=.cache/black` or set `BLACK_CACHE_DIR=.cache/black`. _Black_ will then
write the above files to `.cache/black`. The command-line option takes precedence over
`BLACK_CACHE_DIR`, which takes precedence over `XDG_CACHE_HOME`.

### Disabling the cache with --no-cache

If you need Black to always perform a fresh analysis and not consult or update the
on-disk cache, use the `--no-cache` flag. When provided, Black will neither read from
nor write to the per-user cache. This is useful for debugging, for CI runs where you
want a deterministic fresh run, or when you suspect cache corruption. If combined with
`--cache-dir`, `--no-cache` takes precedence and the specified cache directory is not
created or used.

Example:

```console
python -m black --no-cache .
```

## .gitignore

If `--exclude` is not set, _Black_ will automatically ignore files and directories in
`.gitignore` file(s), if present.

If you want _Black_ to continue using `.gitignore` while also configuring the exclusion
rules, please use `--extend-exclude`.

## Explaining why a file is selected or ignored

To debug file discovery, pass `--explain-file-selection FILE` together with the
directory that should be scanned as `SRC`. _Black_ performs the exact same recursive
scan it would run for formatting, but only reports whether `FILE` would be selected and
the first rule that decides its fate:

```console
$ black --explain-file-selection notes.txt .
/proj/notes.txt would not be selected: does not match the --include regular expression
```

The possible reasons are:

- a `.gitignore` rule, including the file and line number of the rule that took effect
  (nested `.gitignore` files and negation rules are handled exactly like in a normal
  scan);
- an ancestor directory being excluded before the scan could reach the file (by
  `.gitignore` or any exclusion regex);
- the `--exclude`, `--extend-exclude` or `--force-exclude` regular expressions, checked
  in that order;
- the file not matching the `--include` regular expression;
- the path being a symbolic link that points outside the project root.

The checks use the same project root, path normalization and priority as a normal
recursive scan, and `.gitignore` files inside directories that are excluded before
being reached are not read. `FILE` must be an existing file inside the `SRC` directory;
a missing, invalid or out-of-directory target is reported as an error. The explanation
mode never reads or formats the file's contents, does not create or update the cache and
does not modify any files.

The exit code is `0` when the file would be selected, `1` when it would not be selected,
and `2` on an invocation error.
