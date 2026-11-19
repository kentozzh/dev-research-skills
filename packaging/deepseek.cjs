const { dirname } = require("node:path");
const { readSkills } = require("./read-skills.cjs");

exports.name = "dev-research-skills";
exports.inject = ["skills"];
exports.apply = function apply(ctx) {
  for (const skill of readSkills()) {
    ctx.skills.register({
      ...skill,
      source: "runtime",
      resourceBase: { kind: "directory", path: dirname(skill.path) },
    });
  }
};
