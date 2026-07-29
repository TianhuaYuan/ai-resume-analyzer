"""Fix test_mcp_graph.py: add evaluate mock after mcp_generate blocks."""

with open('tests/test_mcp_graph.py', 'r', encoding='utf-8') as f:
    content = f.read()

evaluate_mock = '''
                patch(
                    'services.agentic_rag.generate.with_retry',
                    new_callable=AsyncMock,
                    return_value=('{"completeness": 8, "accuracy": 8, "source_credibility": 7, "feedback": "good"}', {}),
                ),
'''

# Find mcp_generate blocks: each has closing '):' 2 lines after return_value line
# Insert evaluate mock after that closing line
target_str = "services.agentic_rag.mcp_nodes.mcp_generate"
insert_count = 0

while target_str in content:
    idx = content.index(target_str)
    # Find the closing '):' after this block
    block_end = content.index('\n', idx)
    block_end = content.index('\n', block_end + 1)
    block_end = content.index('\n', block_end + 1)
    # Check if the line at block_end starts with spaces and contains '):'
    end_line_start = content.rfind('\n', 0, block_end) + 1
    line = content[end_line_start:content.index('\n', end_line_start)]
    while not line.strip().endswith('):'):
        next_nl = content.index('\n', end_line_start + 1)
        end_line_start = next_nl + 1
        line = content[end_line_start:content.index('\n', end_line_start)]

    # Insert evaluate mock after '):'
    insert_pos = content.index('\n', end_line_start) + 1
    content = content[:insert_pos] + evaluate_mock + '\n            ' + content[insert_pos:]
    insert_count += 1

with open('tests/test_mcp_graph.py', 'w', encoding='utf-8') as f:
    f.write(content)
print(f'Done - {insert_count} evaluate mocks added')
