# -*- coding: utf-8 -*-
"""markdown -> LaTeX(xelatex/ctex)转换器,针对本项目报告。

用法:python md2tex.py 输入.md 输出.tex
"""
import re
import sys

EMOJI = {
    "✅": "[通过]", "❌": "[失败]", "⚠️": "[警告]", "⚠": "[警告]",
    "📄": "", "⟳": "->", "👋": "", "★": "*",
    "→": r"$\rightarrow$", "↔": r"$\leftrightarrow$", "↑": r"$\uparrow$",
    "│": "|", "─": "-", "═": "=", "├": "|", "└": "`", "┌": "", "┐": "",
    "▶": ">",
}


def emoji_replace(s):
    for k, v in EMOJI.items():
        s = s.replace(k, v)
    return s


def esc(s):
    s = s.replace("\\", r"\textbackslash{}")
    s = s.replace("{", r"\{").replace("}", r"\}")
    s = s.replace("$", r"\$").replace("&", r"\&")
    s = s.replace("#", r"\#").replace("%", r"\%")
    s = s.replace("_", r"\_").replace("^", r"\textasciicircum{}")
    s = s.replace("~", r"\textasciitilde{}")
    s = s.replace("<", r"\textless{}").replace(">", r"\textgreater{}")
    return s


def inline(md):
    md = emoji_replace(md)
    subs = []

    def store(item):
        subs.append(item)
        return "\x00%d\x00" % (len(subs) - 1)

    md = re.sub(r"\*\*(.+?)\*\*", lambda m: store(("bf", m.group(1))), md)
    md = re.sub(r"`([^`]+)`", lambda m: store(("tt", m.group(1))), md)
    md = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                lambda m: store(("link", m.group(1), m.group(2))), md)
    md = re.sub(r"\[(x| )\]", lambda m: "[已完成]" if m.group(1) == "x" else "[待办]", md)
    md = esc(md)

    def restore(m):
        item = subs[int(m.group(1))]
        if item[0] == "bf":
            return r"\textbf{" + esc(item[1]) + r"}"
        if item[0] == "tt":
            return r"\texttt{" + esc(item[1]) + r"}"
        if item[0] == "link":
            return item[1] + r" (\url{" + esc(item[2]) + r"})"
        return ""

    return re.sub(r"\x00(\d+)\x00", restore, md)


def convert(md):
    lines = md.split("\n")
    n = len(lines)
    out = []
    list_buf, list_kind = [], None
    i = 0

    def flush_list():
        nonlocal list_buf, list_kind
        if not list_buf:
            return
        env = "enumerate" if list_kind == "o" else "itemize"
        out.append("\\begin{%s}" % env)
        for it in list_buf:
            out.append("  \\item " + inline(it))
        out.append("\\end{%s}" % env)
        list_buf, list_kind = [], None

    while i < n:
        line = lines[i].rstrip()
        s = line.strip()
        if s == "":
            flush_list()
            i += 1
            continue
        if s.startswith("```"):
            flush_list()
            i += 1
            code = []
            while i < n and not lines[i].strip().startswith("```"):
                code.append(emoji_replace(lines[i]))
                i += 1
            i += 1
            out.append("\\begin{verbatim}\n" + "\n".join(code) + "\n\\end{verbatim}")
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            flush_list()
            cmd = {1: "\\section", 2: "\\subsection", 3: "\\subsubsection"}[len(m.group(1))]
            out.append("%s{%s}" % (cmd, inline(m.group(2))))
            i += 1
            continue
        if s == "---":
            flush_list()
            out.append("\\bigskip\\hrule\\bigskip")
            i += 1
            continue
        if s.startswith(">"):
            flush_list()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(inline(lines[i].strip()[1:].strip()))
                i += 1
            out.append("\\begin{quote}\n" + "\n".join(quote) + "\n\\end{quote}")
            continue
        m = re.match(r"^[-*]\s+(.*)$", s)
        if m:
            list_kind = "u"
            list_buf.append(m.group(1))
            i += 1
            continue
        m = re.match(r"^\d+[\.\)]\s+(.*)$", s)
        if m:
            list_kind = "o"
            list_buf.append(m.group(1))
            i += 1
            continue
        if "|" in s and i + 1 < n and re.match(r"^\s*\|?[\s:|\-]+\|?$", lines[i + 1].strip()):
            flush_list()
            header = [c.strip() for c in s.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and "|" in lines[i]:
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append([inline(c) for c in row])
                i += 1
            ncols = len(header)
            out.append("\\begin{center}")
            out.append("\\begin{tabular}{%s}" % ("|c|" * ncols))
            out.append("  \\hline")
            out.append("  " + " & ".join(inline(h) for h in header) + r" \\ \hline")
            for row in rows:
                row = row + [""] * (ncols - len(row))
                out.append("  " + " & ".join(row[:ncols]) + r" \\ \hline")
            out.append("\\end{tabular}")
            out.append("\\end{center}")
            continue
        flush_list()
        para = []
        while i < n and lines[i].strip() and not lines[i].strip().startswith(("#", "```", ">", "-", "*", "|", "1.", "2.", "3.")):
            para.append(inline(lines[i].strip()))
            i += 1
        if para:
            out.append("\n".join(para))
            out.append("")
    flush_list()
    return "\n".join(out)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    md = open(src, encoding="utf-8").read()
    body = convert(md)
    title = "Paper Reader 调试过程与心得"
    m = re.search(r"^#\s+(.+)$", md, re.M)
    if m:
        title = m.group(1).strip()
    tex = """\\documentclass[11pt]{ctexart}
\\usepackage[margin=2.2cm]{geometry}
\\usepackage{xcolor,booktabs,hyperref}
\\usepackage{enumitem}
\\setlist{nosep, leftmargin=1.6em}
\\hypersetup{colorlinks=true, linkcolor=blue, urlcolor=blue}
\\setCJKmonofont{Microsoft YaHei}[Scale=0.85]
\\setmonofont{Consolas}[Scale=0.85]
\\begin{document}
\\begin{center}
{\\LARGE\\bfseries %s}
\\end{center}
\\vspace{0.6em}
%s
\\end{document}
""" % (title, body)
    open(dst, "w", encoding="utf-8").write(tex)
    print("written:", dst)


if __name__ == "__main__":
    main()
