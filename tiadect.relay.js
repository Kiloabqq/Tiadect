function sendToChatGPT() {
  const msg = document.getElementById("copilot-input").value;
  log("Microsoft Copilot", msg);
  route("ChatGPT", msg);
}

function sendToCopilot() {
  const msg = document.getElementById("chatgpt-input").value;
  log("ChatGPT", msg);
  route("Microsoft Copilot", msg);
}

function log(agent, msg) {
  const logId = agent === "Microsoft Copilot" ? "copilot-log" : "chatgpt-log";
  const viewer = document.getElementById("viewer-log");
  const timestamp = new Date().toISOString();
  const entry = `[${timestamp}] ${agent}: ${msg}\n`;
  document.getElementById(logId).textContent += entry;
  viewer.textContent += entry;
}

function route(target, msg) {
  const inputId = target === "Microsoft Copilot" ? "copilot-input" : "chatgpt-input";
  document.getElementById(inputId).value = msg;
}