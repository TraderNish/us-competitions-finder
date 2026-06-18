import { JSDOM } from "jsdom";
import fs from "fs";

const html = fs.readFileSync("index.html", "utf8");
const dataJs = fs.readFileSync("competitions.js", "utf8");
const DATA = JSON.parse(fs.readFileSync("competitions.json", "utf8"));

const errors = [];
const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
const { window } = dom;
const doc = window.document;
window.onerror = e => errors.push(e);
// emulate file:// (no working fetch) so the embedded-data fallback path is tested
window.fetch = () => Promise.reject(new Error("no fetch (file://)"));

window.eval(dataJs);                        // sets window.__DATA__
const inline = html.split("</script>").find(s => s.includes("REPORT_EMAIL"))
  .split("<script>").pop();
try { window.eval(inline); } catch (e) { errors.push("inline threw: " + e.message); }

// the boot path is async (fetch rejects -> fallback); flush microtasks
await new Promise(r => setTimeout(r, 50));

let pass = 0, fail = 0;
const check = (name, cond, extra="") => { cond ? pass++ : fail++;
  console.log(`${cond?"OK  ":"FAIL"}  ${name}${extra?"  — "+extra:""}`); };

const cards = () => [...doc.querySelectorAll("#grid .card")];
const count = () => +doc.getElementById("rowcount").textContent;
const set = (id, v) => { const e = doc.getElementById(id);
  if (e.type === "checkbox") e.checked = v; else e.value = v;
  e.dispatchEvent(new window.Event("input")); };

const activeCount = DATA.competitions.filter(r => r.active).length;

check("no JS errors", errors.length === 0, errors.join(" | "));
check("renders all active competitions", count() === activeCount,
  `rendered=${count()} active=${activeCount}`);
check("discontinued GeoBee is NOT shown",
  !cards().some(c => c.querySelector("h2").textContent.includes("GeoBee")));
check("banner reports refresh state",
  /refreshed/i.test(doc.getElementById("banner").textContent));

// subject filter
set("subject", "math");
const mathExp = DATA.competitions.filter(r=>r.active && r.subjects.includes("math")).length;
check("subject=math", count() === mathExp, `got=${count()} exp=${mathExp}`);
set("subject", "");

// grade filter (exact list membership)
set("grade", "3");
const g3 = DATA.competitions.filter(r=>r.active && r.grades.includes(3)).length;
check("grade=3", count() === g3, `got=${count()} exp=${g3}`);
set("grade", "");

// format filter
set("format", "online");
const onl = DATA.competitions.filter(r=>r.active && r.format==="online").length;
check("format=online", count() === onl, `got=${count()} exp=${onl}`);
set("format", "");

// cost = free
set("cost", "free");
const freeExp = DATA.competitions.filter(r=>r.active &&
  (r.cost||"").toLowerCase().includes("free") && !(r.cost||"").toLowerCase().includes("fee")).length;
check("cost=free", count() === freeExp, `got=${count()} exp=${freeExp}`);
set("cost", "");

// Online option only
set("onlineonly", true);
const onlineExp = DATA.competitions.filter(r=>r.active && r.access?.online_option).length;
check("online option only", count() === onlineExp, `got=${count()} exp=${onlineExp}`);
set("onlineonly", false);

// deadline filter -> only records with a known deadline within the window
set("deadline", "30");
const within30 = DATA.competitions.filter(r => {
  if (!r.active || !r.next_deadline) return false;
  const d = Math.round((new Date(r.next_deadline+"T00:00:00") -
    new Date(new Date().toDateString())) / 86400000);
  return d >= 0 && d <= 30;
}).length;
check("deadline-within-30 matches known deadlines", count() === within30,
  `got=${count()} exp=${within30}`);
set("deadline", "");

// search
set("q", "geography");
check("search 'geography' finds the IAC geography bee",
  cards().some(c => c.querySelector("h2").textContent.includes("Geography")) && count() > 0,
  `rows=${count()}`);
set("q", "");

// verified badges render, and unverified ones are flagged
const verifiedTxt = cards().map(c => c.querySelector(".verified").textContent).join(" ");
check("verified badges present", verifiedTxt.includes("verified"));
check("unverified entries are flagged", verifiedTxt.includes("unverified"));

// every card has a working register link
check("every card links out",
  cards().every(c => /^https?:\/\//.test(c.querySelector("a.reg").href)));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
