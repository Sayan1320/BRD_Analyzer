/**
 * Export utilities for analysis results.
 * Supports Markdown download, JSON download, and clipboard copy.
 * Req 10.7, 10.8, 10.9
 */

function triggerDownload(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function buildMarkdown(analysisData) {
  const { analysis, filename } = analysisData;
  const {
    executive_summary,
    user_stories = [],
    acceptance_criteria = [],
    gap_flags = [],
    tokens_used,
    processing_time_ms,
    model_used,
  } = analysis;

  const generated = new Date().toISOString();

  const lines = [];

  lines.push("# Requirement Analysis Report");
  lines.push(`Generated: ${generated}`);
  lines.push(
    `Document: ${filename} | Model: ${model_used} | Tokens: ${tokens_used} | Time: ${processing_time_ms}ms`
  );
  lines.push("");

  lines.push("## Executive Summary");
  lines.push(executive_summary ?? "");
  lines.push("");

  lines.push("## User Stories");
  lines.push("| ID | Role | Feature | Benefit | Priority |");
  lines.push("|---|---|---|---|---|");
  for (const s of user_stories) {
    lines.push(`| ${s.id} | ${s.role} | ${s.feature} | ${s.benefit} | ${s.priority} |`);
  }
  lines.push("");

  lines.push("## Acceptance Criteria");
  for (const ac of acceptance_criteria) {
    lines.push(`### ${ac.story_id}`);
    if (ac.given) {
      lines.push(`- Given ${ac.given}`);
      lines.push(`- When ${ac.when}`);
      lines.push(`- Then ${ac.then}`);
    } else {
      for (const criterion of ac.criteria ?? []) {
        lines.push(`- Given ${criterion.given}`);
        lines.push(`- When ${criterion.when}`);
        lines.push(`- Then ${criterion.then}`);
      }
    }
    lines.push("");
  }

  lines.push("## Gap Flags");
  lines.push("| Type | Severity | Description |");
  lines.push("|---|---|---|");
  for (const flag of gap_flags) {
    lines.push(`| ${flag.type} | ${flag.severity} | ${flag.description} |`);
  }
  lines.push("");

  return lines.join("\n");
}

export function exportAsMarkdown(analysisData, filename) {
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const md = buildMarkdown(analysisData);
  triggerDownload(md, `analysis_report_${ts}.md`, "text/markdown");
}

export function exportAsJSON(analysisData, filename) {
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const json = JSON.stringify(analysisData, null, 2);
  triggerDownload(json, `analysis_${filename}_${ts}.json`, "application/json");
}

export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
