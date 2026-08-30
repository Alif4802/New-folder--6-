from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class WordBox:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: Optional[float] = None

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)

    @property
    def width(self) -> float:
        return max(1.0, self.x1 - self.x0)

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0


@dataclass
class TextLine:
    words: List[WordBox]
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class TextBlock:
    lines: List[TextLine]
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_number: int


def cluster_words_into_lines(words: List[WordBox]) -> List[TextLine]:
    """
    Cluster word boxes into horizontal lines based on vertical overlap tolerance,
    then sort lines top-to-bottom and words within lines left-to-right.
    """
    if not words:
        return []

    # Sort words primarily by top coordinate
    sorted_words = sorted(words, key=lambda w: (w.y0, w.x0))

    # Cluster words whose vertical center falls within the vertical bounds of an existing line cluster
    clusters: List[List[WordBox]] = []

    for word in sorted_words:
        placed = False
        for cluster in clusters:
            # Calculate average vertical bounds of cluster
            avg_y0 = sum(w.y0 for w in cluster) / len(cluster)
            avg_y1 = sum(w.y1 for w in cluster) / len(cluster)
            avg_height = avg_y1 - avg_y0
            tolerance = max(4.0, avg_height * 0.45)

            if abs(word.center_y - (avg_y0 + avg_y1) / 2.0) <= tolerance:
                cluster.append(word)
                placed = True
                break

        if not placed:
            clusters.append([word])

    # Convert clusters to sorted TextLine objects
    lines: List[TextLine] = []
    for cluster in clusters:
        # Sort words in line strictly from left to right
        sorted_cluster = sorted(cluster, key=lambda w: w.x0)

        # Reconstruct line text with natural spacing
        line_text_parts: List[str] = []
        for i, w in enumerate(sorted_cluster):
            line_text_parts.append(w.text)

        line_text = " ".join(line_text_parts).strip()
        if not line_text:
            continue

        lx0 = min(w.x0 for w in sorted_cluster)
        ly0 = min(w.y0 for w in sorted_cluster)
        lx1 = max(w.x1 for w in sorted_cluster)
        ly1 = max(w.y1 for w in sorted_cluster)

        lines.append(
            TextLine(
                words=sorted_cluster,
                text=line_text,
                x0=round(lx0, 2),
                y0=round(ly0, 2),
                x1=round(lx1, 2),
                y1=round(ly1, 2),
            )
        )

    # Sort lines strictly top to bottom
    lines.sort(key=lambda l: (l.y0, l.x0))
    return lines


def group_lines_into_blocks(lines: List[TextLine], page_number: int) -> List[TextBlock]:
    """
    Group lines into coherent paragraph/content blocks using vertical gap distance.
    """
    if not lines:
        return []

    blocks: List[TextBlock] = []
    current_cluster: List[TextLine] = [lines[0]]

    for i in range(1, len(lines)):
        prev_line = current_cluster[-1]
        curr_line = lines[i]

        vertical_gap = curr_line.y0 - prev_line.y1
        avg_line_height = (prev_line.height + curr_line.height) / 2.0

        # If vertical gap exceeds 1.5x line height or if previous line was a short heading, break block
        if vertical_gap > max(12.0, avg_line_height * 1.5):
            # Finalize previous block
            bx0 = min(l.x0 for l in current_cluster)
            by0 = min(l.y0 for l in current_cluster)
            bx1 = max(l.x1 for l in current_cluster)
            by1 = max(l.y1 for l in current_cluster)
            block_text = "\n".join(l.text for l in current_cluster).strip()

            blocks.append(
                TextBlock(
                    lines=current_cluster,
                    text=block_text,
                    x0=round(bx0, 2),
                    y0=round(by0, 2),
                    x1=round(bx1, 2),
                    y1=round(by1, 2),
                    page_number=page_number,
                )
            )
            current_cluster = [curr_line]
        else:
            current_cluster.append(curr_line)

    if current_cluster:
        bx0 = min(l.x0 for l in current_cluster)
        by0 = min(l.y0 for l in current_cluster)
        bx1 = max(l.x1 for l in current_cluster)
        by1 = max(l.y1 for l in current_cluster)
        block_text = "\n".join(l.text for l in current_cluster).strip()

        blocks.append(
            TextBlock(
                lines=current_cluster,
                text=block_text,
                x0=round(bx0, 2),
                y0=round(by0, 2),
                x1=round(bx1, 2),
                y1=round(by1, 2),
                page_number=page_number,
            )
        )

    return blocks
