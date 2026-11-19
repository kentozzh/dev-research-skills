import catalog from "./packaging/read-skills.cjs";

// OpenCode 1.x discovers skill directories through its config hook.
export async function DevResearchPlugin() {
  return {
    async config(config) {
      if (Array.isArray(config.skills)) return;
      config.skills ??= {};
      config.skills.paths ??= [];
      if (!config.skills.paths.includes(catalog.skillsDirectory)) {
        config.skills.paths.push(catalog.skillsDirectory);
      }
    },
  };
}

// OpenCode 2.x registers skills with their absolute SKILL.md resource paths.
export default {
  id: "dev-research-skill",
  server: DevResearchPlugin,
  async setup(ctx) {
    if (!ctx.skill?.transform) return;
    const skills = catalog.readSkills();
    await ctx.skill.transform(draft => {
      for (const skill of skills) draft.add({ id: skill.name, ...skill });
    });
  },
};
