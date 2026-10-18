"""Helpers the browser tests call directly (touch gestures, layout checks)."""


PINCH_JS = """
async ([sel, distances, frameGaps]) => {
  const el = document.querySelector(sel);
  const r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + Math.min(r.height / 2, 200);
  const touches = d => [0, 1].map(i => new Touch({ identifier: i, target: el,
                                                   clientX: cx + (i ? d / 2 : -d / 2), clientY: cy }));
  const fire = (type, list, changed) => el.dispatchEvent(new TouchEvent(type, {
    touches: list, targetTouches: list, changedTouches: changed || list, bubbles: true, cancelable: true }));
  const frame = () => new Promise(res => requestAnimationFrame(() => res()));
  fire("touchstart", touches(distances[0]));
  for (let i = 1; i < distances.length; i++) {
    fire("touchmove", touches(distances[i]));
    for (let f = 0; f < (frameGaps[i] || 0); f++) await frame();
  }
  fire("touchend", [], touches(distances.at(-1)));     // both fingers lift together
}
"""


def pinch(page, selector, distances, frame_gaps=None):
    """Two-finger pinch on `selector`: touchstart at distances[0], touchmove through the rest, touchend.
    frame_gaps[i] = animation frames to wait after move i (0 = lift fingers before the page can repaint)."""
    page.evaluate(PINCH_JS, [selector, distances, frame_gaps or [1] * len(distances)])


def text_size(page):
    return page.evaluate("[document.documentElement.style.fontSize, localStorage.getItem('cuesta-mbb-textsize')]")


def horizontal_overflow(page):
    """Elements sticking out past the right edge of the viewport (empty list = nothing scrolls sideways)."""
    return page.evaluate("""() => {
      const de = document.documentElement, w = de.clientWidth;
      if (de.scrollWidth <= w && document.body.scrollWidth <= w) return [];
      const out = [];
      for (const el of document.querySelectorAll('body *')) {
        const r = el.getBoundingClientRect();
        if (r.width && r.right > w + 1 && !el.closest('.leaflet-container'))
          out.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}.${[...el.classList].join('.')} right=${Math.round(r.right)}`);
      }
      return [`scrollWidth=${de.scrollWidth} > clientWidth=${w}`, ...out.slice(0, 15)];
    }""")



def fmt_dur(m):
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"
