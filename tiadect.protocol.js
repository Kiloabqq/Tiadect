// Protocol logic for attribution, roles, and future expansion
const Tiadect = {
  agents: {
    "Microsoft Copilot": {
      role: "Initiator",
      color: "#0f0",
    },
    "ChatGPT": {
      role: "Responder",
      color: "#0ff",
    },
  },
  logAttribution(agent, msg) {
    const role = Tiadect.agents[agent].role;
    return `[${role}] ${agent}: ${msg}`;
  },
};