/** Just enough Markdown for results: headings, lists, tables, bold and italic.
 * Everything becomes React nodes from parsed pieces: nothing is inserted as raw HTML. */

export type Inline = { kind: "text" | "bold" | "italic"; text: string };
export type Block =
  | { kind: "text"; text: string }
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] };

const cells = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());

const isRule = (line: string) => /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/.test(line.trim());
const heading = /^(#{1,4})\s+(.*)$/;
const bullet = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/;

/** **bold** and *italic* (or _italic_) inside one line. Unclosed marks stay as plain text. */
export function parseInline(source: string): Inline[] {
  const out: Inline[] = [];
  const pattern = /\*\*([^*]+)\*\*|\*([^*\s][^*]*)\*|_([^_\s][^_]*)_/g;
  let last = 0;
  for (let match = pattern.exec(source); match; match = pattern.exec(source)) {
    if (match.index > last) out.push({ kind: "text", text: source.slice(last, match.index) });
    if (match[1] !== undefined) out.push({ kind: "bold", text: match[1] });
    else out.push({ kind: "italic", text: match[2] ?? match[3] ?? "" });
    last = match.index + match[0].length;
  }
  if (last < source.length) out.push({ kind: "text", text: source.slice(last) });
  return out;
}

export function parseBlocks(source: string): Block[] {
  const lines = source.split("\n");
  const blocks: Block[] = [];
  let text: string[] = [];
  const flush = () => {
    const joined = text.join("\n").trim();
    if (joined) blocks.push({ kind: "text", text: joined });
    text = [];
  };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (line.trim().startsWith("|") && i + 1 < lines.length && isRule(lines[i + 1])) {
      flush();
      const header = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(cells(lines[i]));
        i += 1;
      }
      i -= 1;
      blocks.push({ kind: "table", header, rows });
      continue;
    }
    const head = heading.exec(line);
    if (head) {
      flush();
      blocks.push({ kind: "heading", level: head[1].length, text: head[2].trim() });
      continue;
    }
    if (bullet.test(line)) {
      flush();
      const items: string[] = [];
      while (i < lines.length && bullet.test(lines[i])) {
        items.push((bullet.exec(lines[i]) as RegExpExecArray)[1].trim());
        i += 1;
      }
      i -= 1;
      blocks.push({ kind: "list", items });
      continue;
    }
    text.push(line);
  }
  flush();
  return blocks;
}
