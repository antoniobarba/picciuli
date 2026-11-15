Use dedicated patch/edit tools for source changes, not shell-generated text.
Avoid Set-Content, Out-File, redirection, and shell replace commands for edits.
Preserve each file's encoding, BOM, line endings, and final-newline behavior.
For scripted transformations, use a standalone script with explicit encoding
and newline handling; avoid nesting source code inside shell strings.
After changes, run git diff --check and relevant tests.
Avoid multiple agents writing to the same file concurrently.