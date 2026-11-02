#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: report-to-pdf.sh REPORT.md [OUTPUT.pdf]

Convert a Markdown period report and its linked PNG graph to PDF using Pandoc
and XeLaTeX. The graph is resolved relative to the Markdown file.

Requires pandoc and xelatex (provided by TeX Live). On Debian/Ubuntu:
  sudo apt install pandoc texlive-xetex fonts-dejavu-core
EOF
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
    usage
    exit 0
fi

if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage >&2
    exit 2
fi

for required_command in pandoc xelatex; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        printf 'Error: %s is required. Install Pandoc and XeLaTeX (TeX Live).\n' \
            "$required_command" >&2
        exit 1
    fi
done

report_path=$1
if [[ ! -f $report_path ]]; then
    printf 'Error: report not found: %s\n' "$report_path" >&2
    exit 1
fi

report_dir=$(cd -- "$(dirname -- "$report_path")" && pwd)
report_path="$report_dir/$(basename -- "$report_path")"

output_path=${2:-"${report_path%.*}.pdf"}
output_dir=$(dirname -- "$output_path")
if [[ ! -d $output_dir ]]; then
    printf 'Error: output directory not found: %s\n' "$output_dir" >&2
    exit 1
fi
output_path="$(cd -- "$output_dir" && pwd)/$(basename -- "$output_path")"
if [[ $output_path == "$report_path" ]]; then
    printf 'Error: output path must not overwrite the Markdown report.\n' >&2
    exit 1
fi

pandoc "$report_path" \
    --from=gfm \
    --standalone \
    --resource-path="$report_dir" \
    --pdf-engine=xelatex \
    --variable=mainfont:"DejaVu Sans" \
    --output="$output_path"

printf 'Created PDF: %s\n' "$output_path"
