"""User profile loader - parses YAML into Pydantic models."""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class Location(BaseModel):
    city: str = ""
    state: str = ""
    country: str = ""
    willing_to_relocate: bool = False
    preferred_locations: list[str] = []


class WorkAuthorization(BaseModel):
    india: str = ""
    us: str = ""
    other: str = ""


class Personal(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: Location = Location()
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    date_of_birth: str = ""
    nationality: str = ""
    work_authorization: WorkAuthorization = WorkAuthorization()


class Education(BaseModel):
    degree: str = ""
    institution: str = ""
    location: str = ""
    graduation_date: str = ""
    gpa: str = ""
    relevant_coursework: list[str] = []
    achievements: list[str] = []


class WorkExperience(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""
    technologies: list[str] = []
    achievements: list[str] = []


class ProgrammingLanguages(BaseModel):
    expert: list[str] = []
    proficient: list[str] = []
    familiar: list[str] = []


class Skills(BaseModel):
    programming_languages: ProgrammingLanguages = ProgrammingLanguages()
    frameworks: list[str] = []
    tools: list[str] = []
    soft_skills: list[str] = []


class Project(BaseModel):
    name: str = ""
    description: str = ""
    technologies: list[str] = []
    url: str = ""
    impact: str = ""


class Certification(BaseModel):
    name: str = ""
    issuer: str = ""
    date: str = ""
    credential_id: str = ""


class Language(BaseModel):
    language: str = ""
    proficiency: str = ""


class SalaryExpectations(BaseModel):
    minimum_inr: int = 0
    minimum_usd: int = 0
    preferred_inr: int = 0
    preferred_usd: int = 0
    open_to_negotiation: bool = True


class JobPreferences(BaseModel):
    target_roles: list[str] = []
    target_industries: list[str] = []
    experience_level: str = ""
    job_type: list[str] = []
    work_mode: list[str] = []
    salary_expectations: SalaryExpectations = SalaryExpectations()
    notice_period: str = ""
    available_from: str = ""
    must_have_keywords: list[str] = []
    nice_to_have_keywords: list[str] = []
    exclude_keywords: list[str] = []


class FAQ(BaseModel):
    question: str = ""
    answer_template: str = ""
    answer: str = ""
    answers: dict[str, str] = {}
    strategy: str = ""


class UserProfile(BaseModel):
    personal: Personal = Personal()
    professional_summary: str = ""
    education: list[Education] = []
    work_experience: list[WorkExperience] = []
    skills: Skills = Skills()
    projects: list[Project] = []
    certifications: list[Certification] = []
    languages: list[Language] = []
    job_preferences: JobPreferences = JobPreferences()
    faq: list[FAQ] = []

    @property
    def all_skills_flat(self) -> list[str]:
        """Return a flat list of all skills for matching."""
        skills = []
        skills.extend(self.skills.programming_languages.expert)
        skills.extend(self.skills.programming_languages.proficient)
        skills.extend(self.skills.programming_languages.familiar)
        skills.extend(self.skills.frameworks)
        skills.extend(self.skills.tools)
        return skills

    @property
    def work_experience_summary(self) -> str:
        """Brief summary of work experience for prompts."""
        parts = []
        for exp in self.work_experience:
            parts.append(f"{exp.title} at {exp.company} ({exp.start_date} - {exp.end_date})")
        return "; ".join(parts)


class ProfileLoader:
    """Loads user profile from YAML into a validated Pydantic model."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir

    def load(self, user: str = "kartik") -> UserProfile:
        """Load and parse user profile."""
        from src.utils.security import validate_safe_path

        users_dir = self.config_dir / "users"
        user_dir = validate_safe_path(users_dir, user)
        profile_path = user_dir / "profile.yaml"

        if not profile_path.exists():
            raise FileNotFoundError(f"User profile not found for user: {user}")

        with open(profile_path) as f:
            data = yaml.safe_load(f) or {}

        return UserProfile(**data)
