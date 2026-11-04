# Using _Black_ with Jupyter Notebooks

_Black_ supports formatting Jupyter Notebooks (`.ipynb` files) natively.

## Installation

To format Jupyter Notebooks, install _Black_ with the `jupyter` extra:

```sh
pip install "black[jupyter]"
```

```{note}
Without the `jupyter` extra, _Black_ will not be able to format `.ipynb` files.
```

## Basic usage

Once installed, you can format notebooks the same way you format Python files:

```sh
black notebook.ipynb
```

You can also format entire directories containing a mix of `.py` and `.ipynb` files:

```sh
black .
```

_Black_ will automatically detect Jupyter Notebooks by their `.ipynb` extension and
format them accordingly.

### Formatting via standard input

If you're piping notebook content on standard input, use the `--ipynb` flag to tell
_Black_ to treat the input as a Jupyter Notebook:

```sh
cat notebook.ipynb | black --ipynb -
```

## What is (and isn't) formatted

_Black_ formats the Python code cells in your notebook while preserving:

- Markdown cells
- Cell outputs
- Cell metadata
- Notebook metadata

Only the source code within Python code cells is reformatted.

### Cells that _Black_ will skip

_Black_ is cautious about formatting notebook cells. The following cells will **not** be
formatted:

- **Automagics** — e.g. `pip install black` (without the `%` prefix)
- **Non-Python cell magics** — e.g.:
  ```python
  %%writefile script.py
  print("hello")
  ```
- **Multiline magics** — e.g.:
  ```python
  %timeit f(1, \
          2, \
          3)
  ```
- **IPython internal calls** — code that `IPython`'s `TransformerManager` would
  transform, e.g.:
  ```python
  get_ipython().system('ls')
  ```
- **Invalid syntax** — as it cannot be safely distinguished from automagics without a
  running IPython kernel.

If you notice a cell is not being formatted, it is likely because it contains one of the
above constructs.

Additionally, _Black_ cannot format Jupyter Notebooks with the `--line-ranges` option.

### Cell magics

_Black_ understands IPython magics, but is conservative about which cells it will
format. By default, _Black_ recognizes standard IPython magics.

#### Custom python cell magics

If you use custom cell magics that contain Python code, you can tell _Black_ about them
using the `--python-cell-magics` flag:

```sh
black --python-cell-magics writefile notebook.ipynb
```

This also works in `pyproject.toml`:

```toml
[tool.black]
python-cell-magics = ["writefile", "my_custom_magic"]
```

### Filtering code cells by tag

Jupyter lets you annotate cells with
[tags](https://jupyter-notebook.readthedocs.io/en/stable/changelog.html#cell-tags)
(stored in each cell's `metadata.tags`). If you only want to format some of the code
cells, pass the `--cell-tags` option:

```sh
black --cell-tags format notebook.ipynb
```

Only code cells carrying at least one of the given tags will be formatted. The option
can be repeated to allow multiple tags (a cell is selected if it contains **any** of
them). When `--cell-tags` is not given (or the configured list is empty), _Black_
formats every code cell, as before. Cells without tags are treated by the same rules,
so they are skipped once `--cell-tags` is in use.

To keep certain cells untouched no matter what, use `--exclude-cell-tags`:

```sh
black --cell-tags format --exclude-cell-tags skip notebook.ipynb
```

Exclusion always takes precedence: a cell carrying an exclude tag is never formatted,
even if it also carries an include tag.

The source, outputs and metadata of cells that are not selected are left completely
unchanged. These options affect direct formatting, `--check` and `--diff` alike.

Both options can be set in `pyproject.toml`:

```toml
[tool.black]
cell-tags = ["format"]
exclude-cell-tags = ["skip", "no-black"]
```

## Integrations

### pre-commit

Simply replace the `black` hook with `black-jupyter`.

```yaml
repos:
  - repo: https://github.com/psf/black-pre-commit-mirror
    rev: 26.10.1
    hooks:
      - id: black-jupyter
        language_version: python3.11
```

See the [source version control integration](../integrations/source_version_control.md)
docs for more examples of using Black with pre-commit.

### GitHub Actions

Set the `jupyter` option to `true`.

```yaml
- uses: psf/black@stable
  with:
    jupyter: true
```

See the [GitHub Actions integration](../integrations/source_version_control.md) docs for
more examples of using Black with GitHub Actions.
