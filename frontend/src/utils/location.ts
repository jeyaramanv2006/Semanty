export function formatLocationLabel(label: string, fileType: string = ''): string {
  if (!label) return '';
  const trimmed = label.trim();

  if (fileType.toLowerCase().startsWith('doc')) {
    const pageMatch = trimmed.match(/Page\s+(\d+(?:\s+of\s+\d+)?)/i);
    if (pageMatch) return `Page ${pageMatch[1]}`;
    const numMatch = trimmed.match(/\b\d+\b/);
    return numMatch ? `Page ${numMatch[0]}` : trimmed.replace(/^Section:\s*/i, '');
  }
  if (fileType.toLowerCase().startsWith('ppt')) {
    const slideMatch = trimmed.match(/Slide\s+(\d+)/i);
    return slideMatch ? `Slide ${slideMatch[1]}` : trimmed.split('·')[0].trim();
  }
  if (fileType.toLowerCase() === 'pdf') {
    const pageMatch = trimmed.match(/Page\s+(\d+(?:\s+of\s+\d+)?)/i);
    return pageMatch ? `Page ${pageMatch[1]}` : trimmed.split('·')[0].trim();
  }
  return trimmed.split('·')[0].trim().replace(/^Section:\s*/i, '');
}
