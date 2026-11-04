import json
from typing import IO, Any

import click

import black


def generate_schema_from_click(
    cmd: click.Command,
) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    for param in cmd.params:
        if not isinstance(param, click.Option) or param.is_eager:
            continue

        assert param.name
        name = param.name.replace("_", "-")

        result[name] = {}

        match param.type:
            case click.types.IntParamType():
                result[name]["type"] = "integer"
            case click.types.StringParamType() | click.types.Path():
                result[name]["type"] = "string"
            case click.types.Choice(choices=choices):
                result[name]["enum"] = choices
            case click.types.BoolParamType():
                result[name]["type"] = "boolean"
            case _:
                msg = f"{param.type!r} not a known type for {param}"
                raise TypeError(msg)

        if param.multiple:
            result[name] = {"type": "array", "items": result[name]}

        result[name]["description"] = param.help

        default = param.to_info_dict()["default"]
        if default is not None and not param.multiple:
            result[name]["default"] = default

    return result


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--schemastore", is_flag=True, help="SchemaStore format")
@click.option("--outfile", type=click.File(mode="w"), help="Write to file")
def main(schemastore: bool, outfile: IO[str]) -> None:
    properties = generate_schema_from_click(black.main)
    del properties["line-ranges"]

    properties["presets"] = {
        "type": "object",
        "description": (
            "Named configuration presets selectable with --preset. Each preset"
            " is a table accepting the same keys as [tool.black], optionally"
            " with an 'extends' key naming another preset (or an ordered list"
            " of presets) it inherits from. A selected preset overrides the"
            " common [tool.black] configuration, and command-line options take"
            " final precedence."
        ),
        "additionalProperties": {
            "type": "object",
            "description": "A named configuration preset.",
            "properties": {
                "extends": {
                    "oneOf": [
                        {
                            "type": "string",
                            "description": (
                                "Name of the preset this preset inherits from."
                            ),
                        },
                        {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Names of the presets this preset inherits from,"
                                " applied in declaration order; later presets"
                                " override earlier ones."
                            ),
                        },
                    ],
                    "description": (
                        "Preset (or ordered list of presets) to inherit"
                        " configuration from."
                    ),
                }
            },
            "additionalProperties": True,
        },
    }

    schema: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": (
            "https://github.com/psf/black/blob/main/src/black/resources/black.schema.json"
        ),
        "$comment": "tool.black table in pyproject.toml",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }

    if schemastore:
        schema["$id"] = "https://json.schemastore.org/partial-black.json"
        # The precise list of unstable features may change frequently, so don't
        # bother putting it in SchemaStore
        schema["properties"]["enable-unstable-feature"]["items"] = {"type": "string"}

    print(json.dumps(schema, indent=2), file=outfile)


if __name__ == "__main__":
    main()
