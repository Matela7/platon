# Skills and skill creation

Platon loads skills from `<backend_root>/skills/<name>/SKILL.md` and startup memory from `<backend_root>/memory/AGENTS.md`. The default backend root is `.platon/agent`; `AGENT_BACKEND_ROOT` can override it. These paths are independent of Codex's global skills and memory.

The supervisor sees skill names and descriptions at startup, reads the matching `SKILL.md` on demand, and receives memory contents automatically. An empty skill directory or placeholder memory supplies no useful procedures or context. These are different from conversation history and Chroma documents. See the official [skills](https://docs.langchain.com/oss/python/deepagents/skills) and [memory](https://docs.langchain.com/oss/python/deepagents/memory) documentation.

`delegate_skill_creator` invokes `SkillCreatorAgent`, a DeepAgent that reads and writes `/skills/` only. It reads the upstream skill-creator guide before authoring, creates instructions and supporting files, and verifies them with filesystem reads. Shell execution, other delegation, document access, and memory updates are unavailable. It does not execute the scripts bundled with the guide. New skills are discovered on the next supervisor invocation.

The complete upstream [LangChain skill-creator](https://github.com/langchain-ai/deepagents/tree/main/libs/code/examples/skills/skill-creator) was installed into `.platon/agent/skills/skill-creator`: `SKILL.md`, `scripts/init_skill.py`, and `scripts/quick_validate.py`. The original files are unchanged. The specialist prompt overrides the guide's Deep Agents Code paths with Platon's `/skills/` path. Runtime data under `.platon/` is ignored by Git; install the directory under a different configured backend root when needed.
