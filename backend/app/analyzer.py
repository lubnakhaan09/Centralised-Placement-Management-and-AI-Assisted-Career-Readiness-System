"""Transparent, deterministic resume completeness and job-keyword heuristics."""
import re
from collections import Counter

from .extraction import KNOWN_SKILLS

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "you", "your", "our", "their", "will", "are", "was", "were", "have", "has", "had", "can", "may", "must", "should", "into", "about", "role", "job", "work", "team", "years", "year", "using", "use", "work", "experience", "required", "requirements", "candidate", "ability", "skills", "skill", "strong", "good", "including", "such", "plus", "preferred", "responsibilities", "knowledge", "within", "across", "ensure", "build", "develop", "support", "based", "provide", "related", "new", "one", "all", "not", "who", "what", "when", "where", "how", "its", "our", "any", "more", "other", "each", "both", "also", "etc", "youll", "youre",
}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.]{1,}", text.lower())
    return [word.strip(".+#") for word in words if len(word.strip(".+#")) >= 3 and word.strip(".+#") not in STOP_WORDS]


def analyze_resume(extracted_text: str, parsed: dict, target_text: str) -> dict:
    target_tokens = _tokens(target_text)
    required = set(target_tokens)
    resume_tokens = set(_tokens(extracted_text))
    overlap = required & resume_tokens
    keyword_score = round(100 * len(overlap) / len(required)) if required else 0

    target_skills = [skill for skill in KNOWN_SKILLS if re.search(rf"(?<![\w+#]){re.escape(skill)}(?![\w+#])", target_text, re.I)]
    resume_skills = {skill.casefold() for skill in parsed.get("skills", [])}
    skill_score = round(100 * sum(skill.casefold() in resume_skills for skill in target_skills) / len(target_skills)) if target_skills else keyword_score

    experience_text = " ".join(parsed.get("experience", []))
    experience_tokens = set(_tokens(experience_text))
    experience_score = round(100 * len(required & experience_tokens) / len(required)) if required else 0

    section_map = {
        "skills": bool(parsed.get("skills")),
        "education": bool(parsed.get("education")),
        "experience": bool(parsed.get("experience")),
        "projects": bool(parsed.get("projects")),
        "certifications": bool(parsed.get("certifications")),
    }
    # ATS is a section-completeness heuristic; it is not a vendor ATS prediction.
    ats_checks = [
        bool(parsed.get("email") or parsed.get("phone")),
        section_map["skills"],
        section_map["education"],
        section_map["experience"],
        section_map["projects"],
    ]
    ats_score = round(100 * sum(ats_checks) / len(ats_checks))
    # This checks text-section structure only, not visual page layout or typography.
    formatting_score = min(100, 40 + 15 * sum(section_map.values()))
    job_match = round(skill_score * 0.4 + keyword_score * 0.35 + experience_score * 0.25)

    strengths = []
    if parsed.get("email") or parsed.get("phone"):
        strengths.append("Contact information was detected.")
    for section, present in section_map.items():
        if present:
            strengths.append(f"A {section} section was detected.")
    if overlap:
        strengths.append(f"The resume contains {len(overlap)} target keywords, including {', '.join(sorted(overlap)[:5])}.")

    missing_keywords = sorted(required - resume_tokens)
    missing_skills = [skill for skill in target_skills if skill.casefold() not in resume_skills]
    weaknesses = [f"No {section} section was detected." for section, present in section_map.items() if not present]
    if missing_skills:
        weaknesses.append(f"Target skills not found: {', '.join(missing_skills)}.")
    elif missing_keywords:
        weaknesses.append(f"Some target keywords were not found ({len(missing_keywords)} missing).")

    recommendations = []
    for section, present in section_map.items():
        if not present and section != "certifications":
            recommendations.append(f"Add a clearly labeled {section} section if it applies to your background.")
    if missing_skills:
        recommendations.append(f"If accurate, add evidence for these role skills: {', '.join(missing_skills)}.")
    if not recommendations:
        recommendations.append("Tailor the summary and experience bullets to the target role using specific, verifiable outcomes.")

    return {
        "ats_score": ats_score,
        "keyword_match_percentage": keyword_score,
        "skill_match_percentage": skill_score,
        "experience_match_percentage": experience_score,
        "formatting_score": formatting_score,
        "job_match_percentage": job_match,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "missing_keywords": sorted(set(missing_skills + missing_keywords))[:30],
        "recommendations": recommendations,
        "scoring_method": "section_and_keyword_heuristic_v1",
    }
