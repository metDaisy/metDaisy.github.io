import unittest

from scripts.notion_parser import (
    AbstractBlockParser,
    BlockParserRegistry,
    FallbackParser,
    ParserContext,
    parse_enhanced_markdown,
    render_blocks,
)


class NotionParserTest(unittest.TestCase):
    def test_registry_accepts_new_parser_without_modifying_existing_parsers(self):
        class CustomParser(AbstractBlockParser):
            def can_handle(self, block):
                return block.get("type") == "custom"

            def do_handle(self, block, context: ParserContext, depth):
                return ["custom block"]

        registry = BlockParserRegistry(
            lambda _block_id: [],
            parsers=[CustomParser(), FallbackParser()],
        )

        self.assertEqual(registry.parse_block({"type": "custom"}), ["custom block"])

    def test_nested_blocks_are_delegated_to_the_registry(self):
        table_rows = [
            {
                "type": "table_row",
                "table_row": {
                    "cells": [[{"plain_text": "제목"}], [{"plain_text": "내용"}]]
                },
            },
            {
                "type": "table_row",
                "table_row": {
                    "cells": [[{"plain_text": "하나"}], [{"plain_text": "둘"}]]
                },
            },
        ]
        children = {
            "toggle": [
                {
                    "type": "bulleted_list_item",
                    "has_children": True,
                    "id": "nested-list",
                    "bulleted_list_item": {"rich_text": [{"plain_text": "부모"}]},
                },
                {"type": "table", "id": "table", "has_children": True, "table": {}},
            ],
            "nested-list": [
                {
                    "type": "to_do",
                    "to_do": {"checked": True, "rich_text": [{"plain_text": "자식"}]},
                }
            ],
            "table": table_rows,
        }

        result = render_blocks(
            [
                {
                    "type": "toggle",
                    "id": "toggle",
                    "has_children": True,
                    "toggle": {"rich_text": [{"plain_text": "열기"}]},
                }
            ],
            children.get,
        )

        self.assertIn('<details markdown="1" open>', result)
        self.assertIn("    - 부모", result)
        self.assertIn("        - [x] 자식", result)
        self.assertIn("| 제목 | 내용 |", result)
        self.assertIn("| 하나 | 둘 |", result)

    def test_code_is_a_leaf_and_does_not_parse_table_like_source(self):
        result = render_blocks(
            [
                {
                    "type": "code",
                    "code": {
                        "language": "html",
                        "rich_text": [{"plain_text": "<table><tr><td>source</td></tr></table>"}],
                    },
                }
            ],
            lambda _block_id: [],
        )

        self.assertIn("```html", result)
        self.assertIn("<table><tr><td>source</td></tr></table>", result)
        self.assertEqual(result.count("| source |"), 0)

    def test_unknown_block_uses_a_visible_fallback_and_keeps_children(self):
        result = render_blocks(
            [
                {
                    "type": "unsupported",
                    "id": "unknown-block",
                    "has_children": True,
                    "unsupported": {},
                }
            ],
            lambda _block_id: [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "자식 내용"}]}}
            ],
        )

        self.assertIn('class="notion-fallback"', result)
        self.assertIn("지원되지 않는 Notion 블록: unsupported", result)
        self.assertIn("Notion에서 열기", result)
        self.assertIn("자식 내용", result)

    def test_enhanced_markdown_preserves_colors_and_normalizes_toggle_children(self):
        source = (
            '문장 {color="yellow_bg"}\n'
            '<details>\n'
            '<summary>토글</summary>\n'
            '\t- 부모\n'
            '\t\t- 자식\n'
            '</details>'
        )

        result = parse_enhanced_markdown(source)

        self.assertIn('notion-color--yellow_bg', result)
        self.assertIn('<details markdown="1" open>', result)
        self.assertIn("    - 자식", result)


if __name__ == "__main__":
    unittest.main()
