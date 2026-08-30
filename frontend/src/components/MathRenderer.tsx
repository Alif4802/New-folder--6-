import React, { useMemo } from 'react';
import katex from 'katex';

interface MathRendererProps {
  latex?: string | null;
  rawText?: string | null;
  inline?: boolean;
  className?: string;
}

interface TextSegment {
  type: 'text' | 'math' | 'display-math';
  content: string;
}

/**
 * Parses mixed prose and LaTeX math delimited by $...$, $$...$$, or \(...\).
 */
function parseMixedText(input: string): TextSegment[] {
  if (!input) return [];

  const segments: TextSegment[] = [];
  // Regex to match $$...$$, $...$, and \(...\)
  const mathRegex = /(\$\$[\s\S]*?\$\$|\$[^\$]+?\$|\\\([\s\S]*?\\\))/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = mathRegex.exec(input)) !== null) {
    const textBefore = input.substring(lastIndex, match.index);
    if (textBefore) {
      segments.push({ type: 'text', content: textBefore });
    }

    const matchedStr = match[0];
    if (matchedStr.startsWith('$$') && matchedStr.endsWith('$$')) {
      segments.push({ type: 'display-math', content: matchedStr.slice(2, -2).trim() });
    } else if (matchedStr.startsWith('$') && matchedStr.endsWith('$')) {
      segments.push({ type: 'math', content: matchedStr.slice(1, -1).trim() });
    } else if (matchedStr.startsWith('\\(') && matchedStr.endsWith('\\)')) {
      segments.push({ type: 'math', content: matchedStr.slice(2, -2).trim() });
    }

    lastIndex = match.index + matchedStr.length;
  }

  const remainingText = input.substring(lastIndex);
  if (remainingText) {
    segments.push({ type: 'text', content: remainingText });
  }

  return segments;
}

/**
 * Render LaTeX math safely with KaTeX, falling back to plain text on error.
 */
function renderKaTeX(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, {
      throwOnError: false,
      displayMode,
      output: 'htmlAndMathml',
    });
  } catch {
    return tex;
  }
}

export const MathRenderer: React.FC<MathRendererProps> = ({
  latex,
  rawText = '',
  inline = true,
  className = '',
}) => {
  const textContent = rawText || '';

  const segments = useMemo(() => {
    return parseMixedText(textContent);
  }, [textContent]);

  const supplementaryLatexHtml = useMemo(() => {
    if (!latex) return null;
    const trimmed = latex.trim();
    if (!trimmed) return null;
    // If rawText already contains this exact latex or rendered content, don't duplicate
    if (textContent.includes(trimmed)) return null;

    // Clean any wrapping $ delimiters if present
    const cleanTex = trimmed.startsWith('$') && trimmed.endsWith('$') ? trimmed.slice(1, -1) : trimmed;
    return renderKaTeX(cleanTex, !inline);
  }, [latex, textContent, inline]);

  // If both textContent and latex are completely empty
  if (segments.length === 0 && !supplementaryLatexHtml) {
    return null;
  }

  return (
    <span className={`math-renderer-root ${className}`}>
      {segments.map((seg, idx) => {
        if (seg.type === 'text') {
          // Render plain English prose preserving spaces and normal typography
          return <span key={idx}>{seg.content}</span>;
        }

        const mathHtml = renderKaTeX(seg.content, seg.type === 'display-math');
        return (
          <span
            key={idx}
            className={seg.type === 'display-math' ? 'display-math mx-1' : 'inline-math px-0.5'}
            dangerouslySetInnerHTML={{ __html: mathHtml }}
          />
        );
      })}

      {supplementaryLatexHtml && (
        <span
          className={inline ? 'inline-math ml-2' : 'display-math block my-1.5'}
          dangerouslySetInnerHTML={{ __html: supplementaryLatexHtml }}
        />
      )}
    </span>
  );
};
