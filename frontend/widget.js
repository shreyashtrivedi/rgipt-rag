/* RGIPT Assistant chat widget. Add to any page with one line:
 *   <script src="https://YOUR-BOT-ADDRESS/widget.js" defer></script>
 * It adds a floating "Ask RGIPT" button that opens the chat in a popup. The chat runs in an
 * iframe, so the host site's CSS and ours can't interfere with each other. */
(function () {
  if (window.__rgiptWidget) return;          // script included twice
  window.__rgiptWidget = true;

  var origin = new URL(document.currentScript.src).origin;   // wherever the bot is hosted
  var css = document.createElement("style");
  css.textContent = [
    "#rgipt-chat-btn{position:fixed;right:20px;bottom:20px;z-index:2147483646;border:0;",
    "border-radius:999px;padding:12px 18px;background:#1f5fbf;color:#fff;cursor:pointer;",
    "font:600 15px system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.25)}",
    "#rgipt-chat-box{position:fixed;right:20px;bottom:80px;z-index:2147483647;width:380px;height:560px;",
    "max-height:calc(100vh - 100px);display:none;flex-direction:column;border-radius:14px;overflow:hidden;",
    "background:#fff;box-shadow:0 8px 30px rgba(0,0,0,.3)}",
    "#rgipt-chat-box.open{display:flex}",
    "#rgipt-chat-bar{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;",
    "background:#1f5fbf;color:#fff;font:600 15px system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}",
    "#rgipt-chat-bar button{border:0;background:none;color:#fff;font-size:22px;line-height:1;cursor:pointer}",
    "#rgipt-chat-box iframe{flex:1;border:0;width:100%}",
    "@media (max-width:480px){#rgipt-chat-box{right:0;bottom:0;width:100%;height:100%;max-height:none;border-radius:0}}"
  ].join("");
  document.head.appendChild(css);

  var btn = document.createElement("button");
  btn.id = "rgipt-chat-btn";
  btn.textContent = "Ask RGIPT";
  btn.setAttribute("aria-label", "Open the RGIPT Assistant chat");

  var box = document.createElement("div");
  box.id = "rgipt-chat-box";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-label", "RGIPT Assistant");
  box.innerHTML = '<div id="rgipt-chat-bar"><span>RGIPT Assistant</span>' +
                  '<button aria-label="Close chat">&times;</button></div>';

  var frame = null;   // created on first open, so the page doesn't load the chat until needed
  function toggle(open) {
    if (open && !frame) {
      frame = document.createElement("iframe");
      frame.src = origin + "/?embed=1";
      frame.title = "RGIPT Assistant chat";
      box.appendChild(frame);
    }
    box.classList.toggle("open", open);
    btn.style.display = open ? "none" : "";
  }
  btn.onclick = function () { toggle(true); };
  box.querySelector("button").onclick = function () { toggle(false); };

  document.body.appendChild(btn);
  document.body.appendChild(box);
})();
