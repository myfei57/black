import contextlib
import json
import pathlib
import re
from contextlib import AbstractContextManager
from contextlib import ExitStack as does_not_raise
from dataclasses import replace

import pytest
from click.testing import CliRunner
from pytest import MonkeyPatch

from black import (
    Mode,
    NothingChanged,
    cell_selected_by_tags,
    format_cell,
    format_file_contents,
    format_file_in_place,
    main,
)
from black.handle_ipynb_magics import (
    Replacement,
    create_token,
    jupyter_dependencies_are_installed,
    unmask_cell,
)
from tests.util import DATA_DIR, get_case_path, read_jupyter_notebook

with contextlib.suppress(ModuleNotFoundError):
    import IPython
pytestmark = pytest.mark.jupyter
pytest.importorskip("IPython", reason="IPython is an optional dependency")
pytest.importorskip("tokenize_rt", reason="tokenize-rt is an optional dependency")

JUPYTER_MODE = Mode(is_ipynb=True)

EMPTY_CONFIG = DATA_DIR / "empty_pyproject.toml"

runner = CliRunner()


def test_noop() -> None:
    src = 'foo = "a"'
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


@pytest.mark.parametrize("n_chars", [1, 2, 3, 4, 5, 17])
def test_create_token_uses_requested_length(n_chars: int) -> None:
    assert len(create_token(n_chars)) == n_chars


def test_unmask_cell_raises_when_token_is_not_unique() -> None:
    replacement = Replacement(mask='b"dead"', src="%time")
    with pytest.raises(NothingChanged):
        unmask_cell(f"{replacement.mask}\nvalue = {replacement.mask}", [replacement])


@pytest.mark.parametrize("fast", [True, False])
def test_trailing_semicolon(fast: bool) -> None:
    src = 'foo = "a" ;'
    result = format_cell(src, fast=fast, mode=JUPYTER_MODE)
    expected = 'foo = "a";'
    assert result == expected


def test_trailing_semicolon_with_comment() -> None:
    src = 'foo = "a" ;  # bar'
    result = format_cell(src, fast=True, mode=JUPYTER_MODE)
    expected = 'foo = "a";  # bar'
    assert result == expected


def test_trailing_semicolon_with_comment_on_next_line() -> None:
    src = "import black;\n\n# this is a comment"
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def test_trailing_semicolon_indented() -> None:
    src = "with foo:\n    plot_bar();"
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def test_trailing_semicolon_noop() -> None:
    src = 'foo = "a";'
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param(JUPYTER_MODE, id="default mode"),
        pytest.param(
            replace(JUPYTER_MODE, python_cell_magics={"cust1", "cust2"}),
            id="custom cell magics mode",
        ),
    ],
)
def test_cell_magic(mode: Mode) -> None:
    src = "%%time\nfoo =bar"
    result = format_cell(src, fast=True, mode=mode)
    expected = "%%time\nfoo = bar"
    assert result == expected


def test_cell_magic_noop() -> None:
    src = "%%time\n2 + 2"
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param(JUPYTER_MODE, id="default mode"),
        pytest.param(
            replace(JUPYTER_MODE, python_cell_magics={"cust1", "cust2"}),
            id="custom cell magics mode",
        ),
    ],
)
@pytest.mark.parametrize(
    "src, expected",
    (
        pytest.param("ls =!ls", "ls = !ls", id="System assignment"),
        pytest.param("!ls\n'foo'", '!ls\n"foo"', id="System call"),
        pytest.param("!!ls\n'foo'", '!!ls\n"foo"', id="Other system call"),
        pytest.param("?str\n'foo'", '?str\n"foo"', id="Help"),
        pytest.param("??str\n'foo'", '??str\n"foo"', id="Other help"),
        pytest.param(
            "%matplotlib inline\n'foo'",
            '%matplotlib inline\n"foo"',
            id="Line magic with argument",
        ),
        pytest.param("%time\n'foo'", '%time\n"foo"', id="Line magic without argument"),
        pytest.param(
            "env =  %env var", "env = %env var", id="Assignment to environment variable"
        ),
        pytest.param(
            "变量 =  %env var",
            "变量 = %env var",
            id="Assignment after non-ASCII characters",
        ),
        pytest.param("env =  %env", "env = %env", id="Assignment to magic"),
    ),
)
def test_magic(src: str, expected: str, mode: Mode) -> None:
    result = format_cell(src, fast=True, mode=mode)
    assert result == expected


@pytest.mark.parametrize(
    "src",
    (
        "%%bash\n2+2",
        "%%html --isolated\n2+2",
        "%%writefile e.txt\n  meh\n meh",
    ),
)
def test_non_python_magics(src: str) -> None:
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


@pytest.mark.skipif(
    IPython.version_info < (8, 3),
    reason="Change in how TransformerManager transforms this input",
)
def test_set_input() -> None:
    src = "a = b??"
    expected = "??b"
    result = format_cell(src, fast=True, mode=JUPYTER_MODE)
    assert result == expected


def test_input_already_contains_transformed_magic() -> None:
    src = '%time foo()\nget_ipython().run_cell_magic("time", "", "foo()\\n")'
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def test_magic_noop() -> None:
    src = "ls = !ls"
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


@pytest.mark.parametrize("fast", [True, False])
@pytest.mark.parametrize(
    "src",
    (
        pytest.param(
            "installed_packages_in_this_environment = !pip list --format=freeze"
            " --disable-pip-version-check",
            id="System assignment",
        ),
        pytest.param(
            "benchmark_result_for_the_training_loop = %timeit -o"
            " train_model(dataset, epochs=10, batch_size=32)",
            id="Line magic assignment",
        ),
        pytest.param(
            "if True:\n    installed_packages_in_this_environment = !pip list"
            " --format=freeze --disable-pip-version-check",
            id="Indented system assignment",
        ),
    ),
)
def test_long_magic_assignment_is_not_wrapped_in_parentheses(
    src: str, fast: bool
) -> None:
    # Wrapping the masked right-hand side in parentheses would put the magic
    # inside them, where IPython no longer recognises it.
    with pytest.raises(NothingChanged):
        format_cell(src, fast=fast, mode=JUPYTER_MODE)


def test_unmask_cell_raises_when_magic_is_no_longer_recognised() -> None:
    replacement = Replacement(mask='b"dead"', src="!ls")
    with pytest.raises(NothingChanged):
        unmask_cell(f"x = (\n    {replacement.mask}\n)", [replacement])


def test_cell_magic_with_magic() -> None:
    src = "%%timeit -n1\nls =!ls"
    result = format_cell(src, fast=True, mode=JUPYTER_MODE)
    expected = "%%timeit -n1\nls = !ls"
    assert result == expected


@pytest.mark.parametrize(
    "src, expected",
    (
        ("\n\n\n%time \n\n", "%time"),
        ("  \n\t\n%%timeit -n4 \t \nx=2  \n\r\n", "%%timeit -n4\nx = 2"),
        (
            "  \t\n\n%%capture \nx=2 \n%config \n\n%env\n\t  \n \n\n",
            "%%capture\nx = 2\n%config\n\n%env",
        ),
    ),
)
def test_cell_magic_with_empty_lines(src: str, expected: str) -> None:
    result = format_cell(src, fast=True, mode=JUPYTER_MODE)
    assert result == expected


@pytest.mark.parametrize(
    "mode, expected_output, expectation",
    [
        pytest.param(
            JUPYTER_MODE,
            "%%custom_python_magic -n1 -n2\nx=2",
            pytest.raises(NothingChanged),
            id="No change when cell magic not registered",
        ),
        pytest.param(
            replace(JUPYTER_MODE, python_cell_magics={"cust1", "cust2"}),
            "%%custom_python_magic -n1 -n2\nx=2",
            pytest.raises(NothingChanged),
            id="No change when other cell magics registered",
        ),
        pytest.param(
            replace(JUPYTER_MODE, python_cell_magics={"custom_python_magic", "cust1"}),
            "%%custom_python_magic -n1 -n2\nx = 2",
            does_not_raise(),
            id="Correctly change when cell magic registered",
        ),
    ],
)
def test_cell_magic_with_custom_python_magic(
    mode: Mode, expected_output: str, expectation: AbstractContextManager[object]
) -> None:
    with expectation:
        result = format_cell(
            "%%custom_python_magic -n1 -n2\nx=2",
            fast=True,
            mode=mode,
        )
        assert result == expected_output


@pytest.mark.parametrize(
    "src",
    (
        "   %%custom_magic \nx=2",
        "\n\n%%custom_magic\nx=2",
        "# comment\n%%custom_magic\nx=2",
        "\n  \n # comment with %%time\n\t\n %%custom_magic # comment \nx=2",
    ),
)
def test_cell_magic_with_custom_python_magic_after_spaces_and_comments_noop(
    src: str,
) -> None:
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def test_cell_magic_nested() -> None:
    src = "%%time\n%%time\n2+2"
    result = format_cell(src, fast=True, mode=JUPYTER_MODE)
    expected = "%%time\n%%time\n2 + 2"
    assert result == expected


def test_cell_magic_with_magic_noop() -> None:
    src = "%%t -n1\nls = !ls"
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def test_automagic() -> None:
    src = "pip install black"
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def test_multiline_magic() -> None:
    src = "%time 1 + \\\n2"
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def test_multiline_no_magic() -> None:
    src = "1 + \\\n2"
    result = format_cell(src, fast=True, mode=JUPYTER_MODE)
    expected = "1 + 2"
    assert result == expected


def test_cell_magic_with_invalid_body() -> None:
    src = "%%time\nif True"
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def test_empty_cell() -> None:
    src = ""
    with pytest.raises(NothingChanged):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def test_entire_notebook_empty_metadata() -> None:
    content = read_jupyter_notebook("jupyter", "notebook_empty_metadata")
    result = format_file_contents(content, fast=True, mode=JUPYTER_MODE)
    expected = (
        "{\n"
        ' "cells": [\n'
        "  {\n"
        '   "cell_type": "code",\n'
        '   "execution_count": null,\n'
        '   "metadata": {\n'
        '    "tags": []\n'
        "   },\n"
        '   "outputs": [],\n'
        '   "source": [\n'
        '    "%%time\\n",\n'
        '    "\\n",\n'
        '    "print(\\"foo\\")"\n'
        "   ]\n"
        "  },\n"
        "  {\n"
        '   "cell_type": "code",\n'
        '   "execution_count": null,\n'
        '   "metadata": {},\n'
        '   "outputs": [],\n'
        '   "source": []\n'
        "  }\n"
        " ],\n"
        ' "metadata": {},\n'
        ' "nbformat": 4,\n'
        ' "nbformat_minor": 4\n'
        "}\n"
    )
    assert result == expected


def test_entire_notebook_trailing_newline() -> None:
    content = read_jupyter_notebook("jupyter", "notebook_trailing_newline")
    result = format_file_contents(content, fast=True, mode=JUPYTER_MODE)
    expected = (
        "{\n"
        ' "cells": [\n'
        "  {\n"
        '   "cell_type": "code",\n'
        '   "execution_count": null,\n'
        '   "metadata": {\n'
        '    "tags": []\n'
        "   },\n"
        '   "outputs": [],\n'
        '   "source": [\n'
        '    "%%time\\n",\n'
        '    "\\n",\n'
        '    "print(\\"foo\\")"\n'
        "   ]\n"
        "  },\n"
        "  {\n"
        '   "cell_type": "code",\n'
        '   "execution_count": null,\n'
        '   "metadata": {},\n'
        '   "outputs": [],\n'
        '   "source": []\n'
        "  }\n"
        " ],\n"
        ' "metadata": {\n'
        '  "interpreter": {\n'
        '   "hash": "e758f3098b5b55f4d87fe30bbdc1367f20f246b483f96267ee70e6c40cb185d8"\n'  # noqa:B950
        "  },\n"
        '  "kernelspec": {\n'
        '   "display_name": "Python 3.8.10 64-bit (\'black\': venv)",\n'
        '   "name": "python3"\n'
        "  },\n"
        '  "language_info": {\n'
        '   "name": "python",\n'
        '   "version": ""\n'
        "  }\n"
        " },\n"
        ' "nbformat": 4,\n'
        ' "nbformat_minor": 4\n'
        "}\n"
    )
    assert result == expected


def test_entire_notebook_no_trailing_newline() -> None:
    content = read_jupyter_notebook("jupyter", "notebook_no_trailing_newline")
    result = format_file_contents(content, fast=True, mode=JUPYTER_MODE)
    expected = (
        "{\n"
        ' "cells": [\n'
        "  {\n"
        '   "cell_type": "code",\n'
        '   "execution_count": null,\n'
        '   "metadata": {\n'
        '    "tags": []\n'
        "   },\n"
        '   "outputs": [],\n'
        '   "source": [\n'
        '    "%%time\\n",\n'
        '    "\\n",\n'
        '    "print(\\"foo\\")"\n'
        "   ]\n"
        "  },\n"
        "  {\n"
        '   "cell_type": "code",\n'
        '   "execution_count": null,\n'
        '   "metadata": {},\n'
        '   "outputs": [],\n'
        '   "source": []\n'
        "  }\n"
        " ],\n"
        ' "metadata": {\n'
        '  "interpreter": {\n'
        '   "hash": "e758f3098b5b55f4d87fe30bbdc1367f20f246b483f96267ee70e6c40cb185d8"\n'  # noqa: B950
        "  },\n"
        '  "kernelspec": {\n'
        '   "display_name": "Python 3.8.10 64-bit (\'black\': venv)",\n'
        '   "name": "python3"\n'
        "  },\n"
        '  "language_info": {\n'
        '   "name": "python",\n'
        '   "version": ""\n'
        "  }\n"
        " },\n"
        ' "nbformat": 4,\n'
        ' "nbformat_minor": 4\n'
        "}"
    )
    assert result == expected


def test_entire_notebook_without_changes() -> None:
    content = read_jupyter_notebook("jupyter", "notebook_without_changes")
    with pytest.raises(NothingChanged):
        format_file_contents(content, fast=True, mode=JUPYTER_MODE)


def test_non_python_notebook() -> None:
    content = read_jupyter_notebook("jupyter", "non_python_notebook")

    with pytest.raises(NothingChanged):
        format_file_contents(content, fast=True, mode=JUPYTER_MODE)


def test_empty_string() -> None:
    with pytest.raises(NothingChanged):
        format_file_contents("", fast=True, mode=JUPYTER_MODE)


def test_unparseable_notebook() -> None:
    path = get_case_path("jupyter", "notebook_which_cant_be_parsed.ipynb")
    msg = rf"File '{re.escape(str(path))}' cannot be parsed as valid Jupyter notebook\."
    with pytest.raises(ValueError, match=msg):
        format_file_in_place(path, fast=True, mode=JUPYTER_MODE)


def test_ipynb_diff_with_change() -> None:
    result = runner.invoke(
        main,
        [
            str(get_case_path("jupyter", "notebook_trailing_newline.ipynb")),
            "--diff",
            f"--config={EMPTY_CONFIG}",
        ],
    )
    expected = "@@ -1,3 +1,3 @@\n %%time\n \n-print('foo')\n+print(\"foo\")\n"
    assert expected in result.output


def test_ipynb_diff_with_no_change() -> None:
    result = runner.invoke(
        main,
        [
            str(get_case_path("jupyter", "notebook_without_changes.ipynb")),
            "--diff",
            f"--config={EMPTY_CONFIG}",
        ],
    )
    expected = "1 file would be left unchanged."
    assert expected in result.output


def test_cache_isnt_written_if_no_jupyter_deps_single(
    monkeypatch: MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    # Check that the cache isn't written to if Jupyter dependencies aren't installed.
    jupyter_dependencies_are_installed.cache_clear()
    nb = get_case_path("jupyter", "notebook_trailing_newline.ipynb")
    tmp_nb = tmp_path / "notebook.ipynb"
    tmp_nb.write_bytes(nb.read_bytes())
    monkeypatch.setattr("black.jupyter_dependencies_are_installed", lambda warn: False)
    result = runner.invoke(
        main, [str(tmp_path / "notebook.ipynb"), f"--config={EMPTY_CONFIG}"]
    )
    assert "No Python files are present to be formatted. Nothing to do" in result.output
    jupyter_dependencies_are_installed.cache_clear()
    monkeypatch.setattr("black.jupyter_dependencies_are_installed", lambda warn: True)
    result = runner.invoke(
        main, [str(tmp_path / "notebook.ipynb"), f"--config={EMPTY_CONFIG}"]
    )
    assert "reformatted" in result.output


def test_cache_isnt_written_if_no_jupyter_deps_dir(
    monkeypatch: MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    # Check that the cache isn't written to if Jupyter dependencies aren't installed.
    jupyter_dependencies_are_installed.cache_clear()
    nb = get_case_path("jupyter", "notebook_trailing_newline.ipynb")
    tmp_nb = tmp_path / "notebook.ipynb"
    tmp_nb.write_bytes(nb.read_bytes())
    monkeypatch.setattr(
        "black.files.jupyter_dependencies_are_installed", lambda warn: False
    )
    result = runner.invoke(main, [str(tmp_path), f"--config={EMPTY_CONFIG}"])
    assert "No Python files are present to be formatted. Nothing to do" in result.output
    jupyter_dependencies_are_installed.cache_clear()
    monkeypatch.setattr(
        "black.files.jupyter_dependencies_are_installed", lambda warn: True
    )
    result = runner.invoke(main, [str(tmp_path), f"--config={EMPTY_CONFIG}"])
    assert "reformatted" in result.output


def test_ipynb_flag(tmp_path: pathlib.Path) -> None:
    nb = get_case_path("jupyter", "notebook_trailing_newline.ipynb")
    tmp_nb = tmp_path / "notebook.a_file_extension_which_is_definitely_not_ipynb"
    tmp_nb.write_bytes(nb.read_bytes())
    result = runner.invoke(
        main,
        [
            str(tmp_nb),
            "--diff",
            "--ipynb",
            f"--config={EMPTY_CONFIG}",
        ],
    )
    expected = "@@ -1,3 +1,3 @@\n %%time\n \n-print('foo')\n+print(\"foo\")\n"
    assert expected in result.output


def test_ipynb_and_pyi_flags() -> None:
    nb = get_case_path("jupyter", "notebook_trailing_newline.ipynb")
    result = runner.invoke(
        main,
        [
            str(nb),
            "--pyi",
            "--ipynb",
            "--diff",
            f"--config={EMPTY_CONFIG}",
        ],
    )
    assert isinstance(result.exception, SystemExit)
    expected = "Cannot pass both `pyi` and `ipynb` flags!\n"
    assert result.output == expected


def test_unable_to_replace_magics(monkeypatch: MonkeyPatch) -> None:
    src = '%%time\na = b"foo"'
    monkeypatch.setattr("secrets.token_hex", lambda _: "foo")
    with pytest.raises(
        AssertionError, match="Black was not able to replace IPython magic"
    ):
        format_cell(src, fast=True, mode=JUPYTER_MODE)


def _make_notebook_with_tags() -> tuple[str, dict]:
    """Build a notebook exercising tagged, untagged and markdown cells."""
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"tags": ["format"], "custom": "keep"},
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": ["1\n"]}
                ],
                "source": ["x=1\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"tags": ["skip"]},
                "outputs": [],
                "source": ["y=2\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": ["z=3\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"tags": ["format", "skip"]},
                "outputs": [],
                "source": ["w=4\n"],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Title\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "outputs": [],
                "source": ["q=5\n"],
            },
        ],
        "metadata": {"language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 4,
    }
    return json.dumps(nb, indent=1, ensure_ascii=False) + "\n", nb


@pytest.mark.parametrize(
    "cell, mode, selected",
    [
        pytest.param(
            {"metadata": {"tags": ["a"]}},
            JUPYTER_MODE,
            True,
            id="tagged cell selected without configured tags",
        ),
        pytest.param(
            {"metadata": {}},
            JUPYTER_MODE,
            True,
            id="cell without tags selected without configured tags",
        ),
        pytest.param(
            {},
            JUPYTER_MODE,
            True,
            id="cell without metadata selected without configured tags",
        ),
        pytest.param(
            {"metadata": {"tags": ["a"]}},
            replace(JUPYTER_MODE, cell_tags={"a"}),
            True,
            id="matching include tag",
        ),
        pytest.param(
            {"metadata": {"tags": ["b"]}},
            replace(JUPYTER_MODE, cell_tags={"a"}),
            False,
            id="non-matching include tag",
        ),
        pytest.param(
            {"metadata": {"tags": []}},
            replace(JUPYTER_MODE, cell_tags={"a"}),
            False,
            id="untagged cell skipped with include tags",
        ),
        pytest.param(
            {"metadata": {}},
            replace(JUPYTER_MODE, cell_tags={"a"}),
            False,
            id="missing tags skipped with include tags",
        ),
        pytest.param(
            {"metadata": {"tags": ["a", "b"]}},
            replace(JUPYTER_MODE, cell_tags={"a"}, exclude_cell_tags={"b"}),
            False,
            id="exclude tag takes precedence over include tag",
        ),
        pytest.param(
            {"metadata": {"tags": ["b"]}},
            replace(JUPYTER_MODE, exclude_cell_tags={"b"}),
            False,
            id="exclude tag only",
        ),
        pytest.param(
            {"metadata": {}},
            replace(JUPYTER_MODE, exclude_cell_tags={"b"}),
            True,
            id="untagged cell unaffected by exclude tags",
        ),
    ],
)
def test_cell_selected_by_tags(cell: dict, mode: Mode, selected: bool) -> None:
    assert cell_selected_by_tags(cell, mode) is selected


def test_cell_tags_default_formats_every_code_cell() -> None:
    content, src_nb = _make_notebook_with_tags()
    result = format_file_contents(content, fast=True, mode=JUPYTER_MODE)
    result_nb = json.loads(result)
    expected_sources = ["x = 1", "y = 2", "z = 3", "w = 4", "# Title\n", "q = 5"]
    actual_sources = ["".join(cell["source"]) for cell in result_nb["cells"]]
    assert actual_sources == expected_sources
    # Outputs and metadata of all cells are carried through untouched.
    for src_cell, result_cell in zip(src_nb["cells"], result_nb["cells"]):
        assert result_cell.get("outputs", []) == src_cell.get("outputs", [])
        assert result_cell.get("metadata", {}) == src_cell.get("metadata", {})


def test_cell_tags_only_formats_matching_cells() -> None:
    content, src_nb = _make_notebook_with_tags()
    mode = replace(JUPYTER_MODE, cell_tags={"format"})
    result = format_file_contents(content, fast=True, mode=mode)
    result_nb = json.loads(result)

    # Cells 0 and 3 carry the "format" tag and both get formatted.
    assert "".join(result_nb["cells"][0]["source"]) == "x = 1"
    assert "".join(result_nb["cells"][3]["source"]) == "w = 4"
    # The differently-tagged cell, the untagged cells and the markdown cell
    # are left exactly as they were (source, outputs and metadata).
    for unchanged_index in (1, 2, 4, 5):
        assert result_nb["cells"][unchanged_index] == src_nb["cells"][unchanged_index]
    # Outputs and metadata (including the tag list) of the formatted cells are
    # preserved; only their source changes.
    for formatted_index in (0, 3):
        assert (
            result_nb["cells"][formatted_index]["outputs"]
            == src_nb["cells"][formatted_index]["outputs"]
        )
        assert (
            result_nb["cells"][formatted_index]["metadata"]
            == src_nb["cells"][formatted_index]["metadata"]
        )
    assert result_nb["metadata"] == src_nb["metadata"]


def test_exclude_cell_tags_takes_precedence() -> None:
    content, src_nb = _make_notebook_with_tags()
    mode = replace(JUPYTER_MODE, cell_tags={"format"}, exclude_cell_tags={"skip"})
    result = format_file_contents(content, fast=True, mode=mode)
    result_nb = json.loads(result)

    assert "".join(result_nb["cells"][0]["source"]) == "x = 1"
    # Cell 3 carries both the include and the exclude tag.
    for unchanged_index in (1, 2, 3, 4, 5):
        assert result_nb["cells"][unchanged_index] == src_nb["cells"][unchanged_index]


def test_exclude_cell_tags_without_include_tags() -> None:
    content, src_nb = _make_notebook_with_tags()
    mode = replace(JUPYTER_MODE, exclude_cell_tags={"skip"})
    result = format_file_contents(content, fast=True, mode=mode)
    result_nb = json.loads(result)

    assert "".join(result_nb["cells"][0]["source"]) == "x = 1"
    assert "".join(result_nb["cells"][1]["source"]) == "y=2\n"
    assert "".join(result_nb["cells"][2]["source"]) == "z = 3"
    assert "".join(result_nb["cells"][3]["source"]) == "w=4\n"
    assert "".join(result_nb["cells"][5]["source"]) == "q = 5"
    assert result_nb["cells"][1] == src_nb["cells"][1]
    assert result_nb["cells"][3] == src_nb["cells"][3]


def test_cell_tags_without_matches_is_noop() -> None:
    content, _ = _make_notebook_with_tags()
    mode = replace(JUPYTER_MODE, cell_tags={"does-not-exist"})
    with pytest.raises(NothingChanged):
        format_file_contents(content, fast=True, mode=mode)


def test_exclude_cell_tags_matching_every_change_is_noop() -> None:
    content, _ = _make_notebook_with_tags()
    mode = replace(JUPYTER_MODE, cell_tags={"format"}, exclude_cell_tags={"format"})
    with pytest.raises(NothingChanged):
        format_file_contents(content, fast=True, mode=mode)


def _write_tagged_notebook(directory: pathlib.Path) -> pathlib.Path:
    content, _ = _make_notebook_with_tags()
    notebook = directory / "tagged_notebook.ipynb"
    notebook.write_text(content, encoding="utf-8")
    return notebook


def test_ipynb_cli_cell_tags_in_place(tmp_path: pathlib.Path) -> None:
    notebook = _write_tagged_notebook(tmp_path)
    result = runner.invoke(
        main,
        [
            str(notebook),
            "--cell-tags",
            "format",
            f"--config={EMPTY_CONFIG}",
        ],
    )
    assert result.exit_code == 0
    assert "1 file reformatted" in result.output

    result_nb = json.loads(notebook.read_text(encoding="utf-8"))
    assert "".join(result_nb["cells"][0]["source"]) == "x = 1"
    assert "".join(result_nb["cells"][1]["source"]) == "y=2\n"
    assert "".join(result_nb["cells"][2]["source"]) == "z=3\n"
    assert "".join(result_nb["cells"][3]["source"]) == "w = 4"
    assert result_nb["cells"][0]["outputs"] == [
        {"output_type": "stream", "name": "stdout", "text": ["1\n"]}
    ]
    assert result_nb["cells"][0]["metadata"] == {
        "tags": ["format"],
        "custom": "keep",
    }


def test_ipynb_cli_cell_tags_diff(tmp_path: pathlib.Path) -> None:
    notebook = _write_tagged_notebook(tmp_path)
    result = runner.invoke(
        main,
        [
            str(notebook),
            "--cell-tags",
            "format",
            "--diff",
            f"--config={EMPTY_CONFIG}",
        ],
    )
    assert result.exit_code == 0
    assert "cell_0" in result.output
    assert "cell_3" in result.output
    assert "+x = 1" in result.output
    assert "+w = 4" in result.output
    # Unselected cells don't show up in the diff.
    assert "cell_1" not in result.output
    assert "cell_2" not in result.output
    assert "y = 2" not in result.output
    assert "z = 3" not in result.output


def test_ipynb_cli_exclude_cell_takes_precedence_diff(
    tmp_path: pathlib.Path,
) -> None:
    notebook = _write_tagged_notebook(tmp_path)
    result = runner.invoke(
        main,
        [
            str(notebook),
            "--cell-tags",
            "format",
            "--exclude-cell-tags",
            "skip",
            "--diff",
            f"--config={EMPTY_CONFIG}",
        ],
    )
    assert result.exit_code == 0
    assert "cell_0" in result.output
    assert "cell_3" not in result.output


def test_ipynb_cli_cell_tags_check_when_nothing_selected(
    tmp_path: pathlib.Path,
) -> None:
    notebook = _write_tagged_notebook(tmp_path)
    result = runner.invoke(
        main,
        [
            str(notebook),
            "--cell-tags",
            "does-not-exist",
            "--check",
            f"--config={EMPTY_CONFIG}",
        ],
    )
    assert result.exit_code == 0
    assert "1 file would be left unchanged" in result.output
    # The file must not have been modified in check mode.
    src_content, _ = _make_notebook_with_tags()
    assert notebook.read_text(encoding="utf-8") == src_content


def test_ipynb_cli_cell_tags_from_pyproject_config(
    tmp_path: pathlib.Path,
) -> None:
    notebook = _write_tagged_notebook(tmp_path)
    config = tmp_path / "pyproject.toml"
    config.write_text(
        '[tool.black]\ncell-tags = ["format"]\nexclude-cell-tags = ["skip"]\n',
        encoding="utf-8",
    )
    result = runner.invoke(main, [str(notebook), f"--config={config}"])
    assert result.exit_code == 0
    assert "1 file reformatted" in result.output

    result_nb = json.loads(notebook.read_text(encoding="utf-8"))
    assert "".join(result_nb["cells"][0]["source"]) == "x = 1"
    assert "".join(result_nb["cells"][1]["source"]) == "y=2\n"
    assert "".join(result_nb["cells"][2]["source"]) == "z=3\n"
    assert "".join(result_nb["cells"][3]["source"]) == "w=4\n"
