// ==UserScript==
// @name         TV D-pad navigation
// @namespace    waydroid-tv-box
// @version      1.1.0
// @description  Move between links, buttons and fields with the remote's arrow keys (grid-like), OK clicks. Runs fully local: no network, no data leaves the page.
// @match        *://*/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==
(() => {
  "use strict";
  if (window.__tvNav) return;
  const TOP = window === window.top;
  // Inside a frame: only frames big enough to be a player/content (skip ad/tracking pixels).
  if (!TOP && (innerWidth < 160 || innerHeight < 100)) return;
  window.__tvNav = true;

  // Sites that already have their own TV remote navigation: leave them alone.
  const OWN_NAV = [/(^|\.)youtube\.com$/.test(location.hostname) && location.pathname.startsWith("/tv"), /(^|\.)netflix\.com$/.test(location.hostname)];
  if (OWN_NAV.some(Boolean)) return;

  const DIRS = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
  const SEL = [
    "a[href]", "button", "input:not([type=hidden])", "select", "textarea", "summary",
    "[tabindex]:not([tabindex='-1'])", "[role=button]", "[role=link]", "[role=tab]", "[role=menuitem]",
    "[role=option]", "[role=checkbox]", "[role=switch]", "[onclick]", "[contenteditable=''], [contenteditable=true]",
    "video", "audio[controls]", "iframe", "embed", "object",
  ].join(",");

  const css = document.createElement("style");
  css.textContent = `
    #tvnav-ring { position: fixed; box-sizing: border-box; z-index: 2147483647; pointer-events: none; border: 4px solid #4da3ff;
      border-radius: 8px; box-shadow: 0 0 0 4px rgba(10,20,40,.55), 0 0 18px 4px rgba(77,163,255,.6);
      transition: left .12s, top .12s, width .12s, height .12s; display: none; }
    #tvnav-hint { position: fixed; z-index: 2147483647; right: 16px; bottom: 16px; padding: 8px 14px;
      background: rgba(20,24,32,.88); color: #fff; font: 600 15px/1.3 system-ui, sans-serif; border-radius: 10px;
      pointer-events: none; opacity: 0; transition: opacity .25s; }
    #tvnav-hint.on { opacity: 1; }`;
  (document.head || document.documentElement).appendChild(css);

  let cur = null;           // element we consider focused
  let hintT = 0;
  const hint = (txt) => {
    let h = document.getElementById("tvnav-hint");
    if (!h) { h = document.createElement("div"); h.id = "tvnav-hint"; document.documentElement.appendChild(h); }
    h.textContent = txt; h.classList.add("on");
    clearTimeout(hintT); hintT = setTimeout(() => h.classList.remove("on"), 1200);
  };

  // Elements up to one screen beyond the edge count too, so "down" walks the page and scrolls it
  // (instead of jumping to a fixed cookie bar at the bottom and getting stuck there).
  const visible = (el, strict) => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return null;
    const sh = strict ? 0 : innerHeight;
    if (r.bottom < -sh || r.top > innerHeight + sh || r.right < 0 || r.left > innerWidth) return null;
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || +s.opacity === 0 || s.pointerEvents === "none") return null;
    if (el.disabled || el.closest("[aria-hidden=true], [inert]")) return null;
    if (/^(IFRAME|EMBED|OBJECT)$/.test(el.tagName) && (r.width < 160 || r.height < 100)) return null;
    if (/^(VIDEO|IFRAME|EMBED|OBJECT)$/.test(el.tagName)) return r;   // players put click layers on top of them
    if (!/^(INPUT|SELECT|TEXTAREA|VIDEO|AUDIO)$/.test(el.tagName) && !el.textContent.trim() &&
        !el.getAttribute("aria-label") && !el.title && !el.querySelector("img, svg, picture, canvas, [style*=background]") &&
        getComputedStyle(el).backgroundImage === "none") return null;     // empty helper elements
    if (r.bottom < 0 || r.top > innerHeight) return r;      // off screen: cannot test what covers it
    // covered by something else (cookie banner backdrop, modal): only the top-most element counts
    const cx = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 1);
    const cy = Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 1);
    const top = document.elementFromPoint(cx, cy);
    if (top && top !== el && !el.contains(top) && !top.contains(el)) {
      const lab = top.closest(SEL);
      if (lab !== el) return null;
    }
    return r;
  };

  const candidates = () => {
    const out = [];
    const seen = new Set();
    for (const el of document.querySelectorAll(SEL)) {
      if (seen.has(el)) continue;
      // nested focusables (span[role=button] inside a[href]): keep the outer one
      const outer = el.parentElement && el.parentElement.closest(SEL);
      if (outer && outer !== el && !/^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(el.tagName)) continue;
      const r = visible(el);
      if (r) { out.push({ el, r }); seen.add(el); }
    }
    // clickable divs/spans with cursor:pointer that are not marked up (common on modern sites)
    for (const el of document.querySelectorAll("div, span, li, img, label")) {
      if (seen.has(el)) continue;
      const q = el.getBoundingClientRect();          // cheap range test first: pages have thousands of divs
      if (q.width < 4 || q.height < 4 || q.bottom < -innerHeight || q.top > 2 * innerHeight) continue;
      if (getComputedStyle(el).cursor !== "pointer" || el.closest(SEL)) continue;
      if (el.parentElement && getComputedStyle(el.parentElement).cursor === "pointer") continue;
      const r = visible(el);
      if (r && r.width * r.height < innerWidth * innerHeight * 0.5) { out.push({ el, r }); seen.add(el); }
    }
    return out;
  };

  // Score: distance along the direction + 3x the sideways offset; overlapping rows/columns win.
  function best(from, dir, list) {
    let pick = null, score = Infinity;
    const fc = { x: from.left + from.width / 2, y: from.top + from.height / 2 };
    for (const c of list) {
      const r = c.r;
      let main, side, overlap;
      if (dir === "down") { main = r.top - from.bottom; overlap = Math.min(r.right, from.right) - Math.max(r.left, from.left); }
      if (dir === "up") { main = from.top - r.bottom; overlap = Math.min(r.right, from.right) - Math.max(r.left, from.left); }
      if (dir === "right") { main = r.left - from.right; overlap = Math.min(r.bottom, from.bottom) - Math.max(r.top, from.top); }
      if (dir === "left") { main = from.left - r.right; overlap = Math.min(r.bottom, from.bottom) - Math.max(r.top, from.top); }
      if (main < -Math.min(from.height, from.width, 12) / 2) continue;   // not in that direction
      main = Math.max(main, 0);
      const cc = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      side = dir === "up" || dir === "down" ? Math.abs(cc.x - fc.x) : Math.abs(cc.y - fc.y);
      if (overlap > 0) side = 0;
      const s = main + side * 3;
      if (s < score) { score = s; pick = c; }
    }
    return pick;
  }

  // The frame is our own overlay (not an outline on the element): sites clip outlines with overflow:hidden.
  let ring = null, raf = 0;
  function track() {
    raf = 0;
    if (!ring) { ring = document.createElement("div"); ring.id = "tvnav-ring"; document.documentElement.appendChild(ring); }
    if (!cur || !document.contains(cur)) { ring.style.display = "none"; return; }
    const r = cur.getBoundingClientRect(), p = 5;
    const k = [r.left, r.top, r.width, r.height].map(Math.round).join();
    still = k === lastK ? still + 1 : 0; lastK = k;
    Object.assign(ring.style, { display: "block", left: r.left - p + "px", top: r.top - p + "px",
      width: r.width + 2 * p + "px", height: r.height + 2 * p + "px" });
    if (still < 30) raf = requestAnimationFrame(track);   // follow smooth scrolling, then sleep (weak TV CPU)
  }
  let still = 0, lastK = "";
  const wake = () => { still = 0; if (!raf && cur) raf = requestAnimationFrame(track); };
  addEventListener("scroll", wake, { passive: true, capture: true });
  addEventListener("resize", wake);
  function setCur(el, r) {
    if (cur) cur.classList.remove("tvnav-focus");
    cur = el;
    el.classList.add("tvnav-focus");
    wake();
    if (/^(IFRAME|EMBED|OBJECT)$/.test(el.tagName)) hint("OK: oynatıcıya gir");
    // Text fields are only highlighted: focusing them would pop up the on-screen keyboard while just passing by.
    // OK focuses them. Leaving a field closes the keyboard.
    const a = document.activeElement;
    if (isText(el)) { if (a && a !== document.body && a !== el) try { a.blur(); } catch (e) {} }
    else if (!/^(IFRAME|EMBED|OBJECT)$/.test(el.tagName)) try { el.focus({ preventScroll: true }); } catch (e) {}
    // not focusable (div play button) or a frame: drop the old focus, else the next key starts from there
    if (!isText(el) && document.activeElement !== el && document.activeElement && document.activeElement !== document.body)
      try { document.activeElement.blur(); } catch (e) {}
    r = r || el.getBoundingClientRect();
    const m = 80;
    if (r.top < m || r.bottom > innerHeight - m || r.left < 0 || r.right > innerWidth)
      el.scrollIntoView({ block: r.height > innerHeight - 2 * m ? "start" : "center", inline: "nearest", behavior: "smooth" });
  }

  const isText = (el) => el && (el.isContentEditable || el.tagName === "TEXTAREA" ||
    (el.tagName === "INPUT" && !/^(button|submit|reset|checkbox|radio|range|color|file|image)$/.test(el.type)));

  // ---- video players -------------------------------------------------------------------------------
  // Players hide their controls until the mouse moves; a fake mousemove over the video brings them back.
  const videos = () => [...document.querySelectorAll("video")].filter((v) => { const r = v.getBoundingClientRect(); return r.width > 160 && r.height > 90; });
  function poke() {
    let any = false;
    for (const v of videos()) {
      const r = v.getBoundingClientRect();
      const x = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 1), y = Math.min(Math.max(r.top + r.height * 0.6, 1), innerHeight - 1);
      const t = document.elementFromPoint(x, y) || v;
      for (const type of ["pointermove", "mousemove", "mouseover"])
        t.dispatchEvent(new (type.startsWith("pointer") ? PointerEvent : MouseEvent)(type, { bubbles: true, clientX: x, clientY: y, view: window }));
      any = true;
    }
    return any;
  }
  const isPlayish = (el) => /play|başlat|oynat/i.test([el.getAttribute("aria-label"), el.title, el.className && el.className.baseVal === undefined ? el.className : "", el.id].join(" "));
  function startEl(list) {      // entering a page/frame with a player: the big play button first, else the video
    const on = list.filter((c) => c.r.bottom > 0 && c.r.top < innerHeight);
    const play = on.filter((c) => isPlayish(c.el) && c.el.tagName !== "VIDEO").sort((a, b) => b.r.width * b.r.height - a.r.width * a.r.height)[0];
    return play || on.find((c) => c.el.tagName === "VIDEO") || null;
  }

  // ---- frames (players are usually an <iframe> from another site) ------------------------------------
  // The script runs in every frame. OK on a frame hands the remote to it; at its edge it hands back.
  const MSG = "__tvnav";
  let inFrame = null;           // parent side: the frame that currently has the remote
  function enterFrame(fr, dir) {
    inFrame = fr;
    if (ring) ring.style.display = "none";
    try { fr.focus(); } catch (e) {}
    try { fr.contentWindow.postMessage({ [MSG]: "enter", dir }, "*"); } catch (e) {}
    // no answer = the script does not run in that frame (sandboxed/blocked): take the remote back
    clearTimeout(ackT);
    ackT = setTimeout(() => {
      if (inFrame !== fr) return;
      inFrame = null; try { fr.blur(); } catch (e) {} window.focus(); setCur(fr);
      hint("Bu oynatıcı kumandayla kullanılamıyor");
    }, 700);
  }
  let ackT = 0;
  function leaveFrame(dir) {    // child side
    if (cur) cur.classList.remove("tvnav-focus");
    cur = null; if (ring) ring.style.display = "none";
    window.parent.postMessage({ [MSG]: "exit", dir }, "*");
  }
  addEventListener("message", (e) => {
    const d = e.data;
    if (!d || typeof d !== "object" || !d[MSG]) return;
    if (d[MSG] === "ack") { clearTimeout(ackT); return; }
    if (d[MSG] === "enter" && e.source === window.parent) {
      window.parent.postMessage({ [MSG]: "ack" }, "*");
      setTimeout(() => {
        poke();
        setTimeout(() => {
          const list = candidates(), s = startEl(list);
          if (s) setCur(s.el, s.r); else move(d.dir || "down", true);
        }, 150);
      }, 0);
    }
    if (d[MSG] === "exit") {
      const fr = [...document.querySelectorAll("iframe, embed, object")].find((f) => { try { return f.contentWindow === e.source; } catch (x) { return false; } });
      if (!fr) return;
      inFrame = null; cur = fr;
      const p = d.dir && best(fr.getBoundingClientRect(), d.dir, candidates().filter((c) => c.el !== fr));
      if (p) setCur(p.el, p.r);
      else { try { fr.blur(); } catch (x) {} window.focus(); setCur(fr); hint("Oynatıcıdan çıkıldı"); }
    }
  });

  function move(dir, entering) {
    const list = candidates().filter((c) => c.el !== cur);
    const alive = cur && document.contains(cur) && visible(cur, true);
    if (!alive) {
      // start at the top-left-most element on screen
      const on = list.filter((c) => c.r.bottom > 0 && c.r.top < innerHeight);
      if (!on.length) return TOP || entering ? scroll(dir) : leaveFrame(dir);
      const s0 = startEl(on);
      if (s0 && !TOP) return setCur(s0.el, s0.r);
      list.length = 0; list.push(...on);
      list.sort((a, b) => (a.r.top - b.r.top) || (a.r.left - b.r.left));
      const first = dir === "up" ? list[list.length - 1] : list[0];
      return setCur(first.el, first.r);
    }
    const p = best(cur.getBoundingClientRect(), dir, list);
    if (p) return setCur(p.el, p.r);
    if (!TOP) {                 // frame edge: scroll the frame if it can, else back to the page
      const dy = dir === "down" ? 1 : dir === "up" ? -1 : 0, se = document.scrollingElement;
      if (se && dy && (dy > 0 ? se.scrollTop + innerHeight < se.scrollHeight - 2 : se.scrollTop > 0)) return scroll(dir);
      return leaveFrame(dir);
    }
    scroll(dir);
  }

  function scroll(dir) {
    const dy = dir === "down" ? 1 : dir === "up" ? -1 : 0, dx = dir === "right" ? 1 : dir === "left" ? -1 : 0;
    const before = [scrollX, scrollY];
    window.scrollBy({ left: dx * innerWidth * 0.6, top: dy * innerHeight * 0.6, behavior: "smooth" });
    setTimeout(() => { if (scrollX === before[0] && scrollY === before[1]) hint(dy > 0 ? "Sayfanın sonu" : dy < 0 ? "Sayfanın başı" : "Kenar"); }, 400);
  }

  function activate(el) {
    if (/^(IFRAME|EMBED|OBJECT)$/.test(el.tagName)) return enterFrame(el, "down");
    if (el.tagName === "VIDEO") {
      // a click layer usually sits on the video: click what is on top (the player's own toggle), else toggle ourselves
      const r = el.getBoundingClientRect(), t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      const was = el.paused;
      if (t && t !== el) t.click();
      setTimeout(() => { if (el.paused === was) { if (was) el.play().catch(() => {}); else el.pause(); } }, 250);
      poke();
      return;
    }
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable) {
      el.focus();
      if (el.tagName === "SELECT" && el.showPicker) try { el.showPicker(); } catch (e) {}
      if (isText(el) || el.tagName === "SELECT") { el.click(); return; }
    }
    el.click();
  }

  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    const a = document.activeElement;
    const dir = DIRS[e.key];
    if (!TOP && (e.key === "Escape" || e.key === "GoBack" || e.key === "BrowserBack")) {
      e.preventDefault(); e.stopPropagation(); return leaveFrame(null);
    }
    if (dir && videos().length && poke() && !cur) {         // controls were hidden: let them appear first
      e.preventDefault(); e.stopPropagation();
      setTimeout(() => move(dir), 150); return;
    }
    if (dir && cur && cur.tagName === "VIDEO" && (dir === "left" || dir === "right") && isFinite(cur.duration)) {
      e.preventDefault(); e.stopPropagation();             // on the video: left/right = -/+10 s
      cur.currentTime = Math.max(0, cur.currentTime + (dir === "left" ? -10 : 10)); poke();
      const m = Math.floor(cur.currentTime / 60), sec = Math.floor(cur.currentTime % 60);
      return hint((dir === "left" ? "−10 sn  " : "+10 sn  ") + m + ":" + String(sec).padStart(2, "0"));
    }
    if (dir) {
      if (isText(a)) {
        // inside a text field: up/down leave it, left/right move the caret until the edge
        const v = a.value ?? a.textContent ?? "";
        const atStart = a.selectionStart === 0 && a.selectionEnd === 0, atEnd = a.selectionStart === v.length;
        if (dir === "left" && !(atStart || a.selectionStart == null)) return;
        if (dir === "right" && !(atEnd || a.selectionStart == null)) return;
        if (a.tagName === "TEXTAREA" && (dir === "up" || dir === "down")) {
          const before = v.slice(0, a.selectionStart);
          if (dir === "up" && before.includes("\n")) return;
          if (dir === "down" && v.slice(a.selectionEnd).includes("\n")) return;
        }
      }
      if (a && a.tagName === "SELECT" && (dir === "up" || dir === "down")) return;  // change option
      if (a && a.type === "range" && (dir === "left" || dir === "right")) return;   // slider
      if (a && /^(VIDEO|AUDIO)$/.test(a.tagName) && (dir === "left" || dir === "right")) return; // seek
      e.preventDefault(); e.stopPropagation();
      if (a && a !== document.body && a !== cur && a.matches && a.matches(SEL)) { cur = a; }
      move(dir);
      return;
    }
    if ((e.key === "Enter" || e.key === " ") && cur && document.contains(cur)) {
      if (a === cur && /^(A|BUTTON|INPUT|TEXTAREA|SELECT|SUMMARY)$/.test(cur.tagName)) {
        if (cur.tagName === "INPUT" && isText(cur)) return;   // Enter in a field = submit (native)
        if (cur.tagName === "A" || cur.tagName === "BUTTON") return;   // native activation
      }
      if (e.key === " " && isText(a)) return;
      e.preventDefault(); e.stopPropagation();
      activate(cur);
    }
  }, true);

  // mouse/touch use: drop our ring so it does not linger at an old place
  document.addEventListener("pointerdown", () => { if (cur) cur.classList.remove("tvnav-focus"); cur = null; }, true);
  // SPA navigation / bfcache: start fresh
  addEventListener("pageshow", () => { cur = null; });
})();
