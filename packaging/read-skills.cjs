const { readdirSync, readFileSync } = require("node:fs");
const path = require("node:path");
const { parse } = require("yaml");

const skillsDirectory = path.resolve(__dirname, "../skills");

function readSkills() {
  const entries = readdirSync(skillsDirectory, { withFileTypes: true });
  return entries.filter(entry => entry.isDirectory()).map(entry => {
    const file = path.join(skillsDirectory, entry.name, "SKILL.md");
    const source = readFileSync(file, "utf8");
    const parts = /^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/.exec(source);
    if (!parts) throw new Error(`Missing frontmatter in ${file}`);
    const { name, description } = parse(parts[1]);
    if (name !== entry.name || typeof description !== "string" || !description.trim()) {
      throw new Error(`Invalid skill metadata in ${file}`);
    }
    return { name, description, path: file, content: parts[2].trim() };
  });
}

module.exports = { readSkills, skillsDirectory };
