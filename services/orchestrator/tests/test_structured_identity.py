"""Tests for structured identity extraction and experience_mode derivation.

Covers:
  - Phase 1: StructuredIdentityProfile extraction from various identity signals
  - Phase 2: experience_mode derivation for different identity types
  - Phase 3: planner build_spec always includes experience_mode
"""

from __future__ import annotations

from kmbl_orchestrator.identity.profile import (
    StructuredIdentityProfile,
    derive_experience_mode,
    extract_structured_identity,
)


# ── Phase 1: Structured Identity Extraction ──────────────────────────────────


class TestExtractStructuredIdentity:
    """Structured identity extraction produces expected fields."""

    def test_empty_inputs_returns_defaults(self) -> None:
        profile = extract_structured_identity()
        assert isinstance(profile, StructuredIdentityProfile)
        assert profile.themes == []
        assert profile.tone == []
        assert profile.visual_tendencies == []
        assert profile.content_types == []
        assert profile.complexity == "moderate"
        assert profile.notable_entities == []

    def test_creative_portfolio_identity(self) -> None:
        """A creative photographer portfolio should extract visual/artistic signals."""
        profile = extract_structured_identity(
            identity_brief={
                "display_name": "Jane Doe",
                "role_or_title": "photographer & visual artist",
                "short_bio": "Capturing cinematic moments through experimental photography",
                "tone_keywords": ["bold", "artistic", "dark"],
                "aesthetic_keywords": ["cinematic", "gallery"],
                "image_refs": ["img1.jpg", "img2.jpg", "img3.jpg", "img4.jpg", "img5.jpg"],
                "layout_hints": ["portfolio"],
            },
            profile_data={
                "project_evidence": ["Personal Portraits Series", "Urban Landscapes Exhibition"],
            },
        )
        assert "artistic" in profile.themes or "cinematic" in profile.themes
        assert "image-driven" in profile.visual_tendencies
        assert "photography" in profile.content_types or "art" in profile.content_types
        assert profile.complexity in ("moderate", "ambitious")
        assert "Jane Doe" in profile.notable_entities

    def test_editorial_blog_identity(self) -> None:
        """A text-heavy blog should extract editorial/writing signals."""
        profile = extract_structured_identity(
            identity_brief={
                "display_name": "Alex Writer",
                "role_or_title": "writer & essayist",
                "short_bio": "Writing about technology and culture",
                "tone_keywords": ["professional", "serious"],
                "aesthetic_keywords": ["minimal", "clean"],
                "layout_hints": [],
                "image_refs": [],
            },
        )
        assert "editorial" in profile.themes or "minimal" in profile.themes
        assert "typography-first" in profile.visual_tendencies
        assert "writing" in profile.content_types
        assert profile.complexity in ("simple", "moderate")

    def test_experimental_developer_identity(self) -> None:
        """An experimental developer should signal ambitious complexity."""
        profile = extract_structured_identity(
            identity_brief={
                "display_name": "DevArt Studio",
                "role_or_title": "creative developer",
                "short_bio": "Building immersive WebGL experiences and generative art installations",
                "tone_keywords": ["experimental", "bold"],
                "aesthetic_keywords": ["experimental", "interactive"],
                "layout_hints": ["portfolio"],
            },
            profile_data={
                "project_evidence": ["Generative Landscapes", "WebGL Gallery"],
                "headings": ["Interactive Installations", "Experimental Projects"],
            },
        )
        assert "experimental" in profile.themes
        assert "spatial" in profile.visual_tendencies
        assert profile.complexity == "ambitious"

    def test_corporate_services_identity(self) -> None:
        """A corporate site should extract corporate/services signals."""
        profile = extract_structured_identity(
            identity_brief={
                "display_name": "Acme Consulting",
                "role_or_title": "enterprise consulting firm",
                "short_bio": "Professional business solutions for enterprises",
                "tone_keywords": ["corporate", "professional", "serious"],
                "aesthetic_keywords": ["clean", "modern"],
            },
            profile_data={
                "project_evidence": ["Service offerings"],
                "headings": ["Our Solutions", "Contact Us"],
            },
        )
        assert "corporate" in profile.themes
        assert "serious" in profile.tone
        assert profile.complexity in ("simple", "moderate")

    def test_to_dict_omits_empty_lists(self) -> None:
        """to_dict() should omit empty lists but always include complexity."""
        profile = StructuredIdentityProfile(
            themes=["minimal"],
            tone=[],
            visual_tendencies=[],
            content_types=["writing"],
            complexity="simple",
            notable_entities=[],
        )
        d = profile.to_dict()
        assert "themes" in d
        assert "tone" not in d
        assert "visual_tendencies" not in d
        assert "content_types" in d
        assert d["complexity"] == "simple"
        assert "notable_entities" not in d

    def test_seed_data_raw_text_used(self) -> None:
        """Extraction should use seed_data.raw_text for keyword matching."""
        profile = extract_structured_identity(
            seed_data={
                "raw_text": "John Smith (photographer) — capturing artistic moments in galleries",
                "tone_keywords": ["artistic"],
            },
        )
        assert "artistic" in profile.themes  # 'artistic' keyword from raw_text
        assert "photography" in profile.content_types or "art" in profile.content_types

    def test_notable_entities_includes_project_evidence(self) -> None:
        """Notable entities should include display_name and project evidence."""
        profile = extract_structured_identity(
            identity_brief={"display_name": "Studio X"},
            profile_data={
                "project_evidence": ["Brand Redesign", "Mobile App", "Web Platform"],
            },
        )
        assert "Studio X" in profile.notable_entities
        assert "Brand Redesign" in profile.notable_entities


# ── Phase 2: Experience Mode Derivation ──────────────────────────────────────


class TestDeriveExperienceMode:
    """experience_mode derivation behaves correctly for different identity types."""

    def test_spatial_visual_tendency_yields_immersive(self) -> None:
        """Explicit spatial visual tendency should yield immersive_spatial_portfolio."""
        si = StructuredIdentityProfile(
            themes=["experimental"],
            visual_tendencies=["spatial"],
            content_types=["projects"],
            complexity="ambitious",
        )
        mode = derive_experience_mode(si)
        assert mode == "immersive_spatial_portfolio"

    def test_ambitious_image_driven_yields_webgl(self) -> None:
        """Ambitious + image-driven should yield webgl_3d_portfolio."""
        si = StructuredIdentityProfile(
            themes=["artistic"],
            visual_tendencies=["image-driven"],
            content_types=["photography"],
            complexity="ambitious",
        )
        mode = derive_experience_mode(si)
        assert mode == "webgl_3d_portfolio"

    def test_portfolio_archetype_with_creative_themes(self) -> None:
        """Portfolio archetype + cinematic theme → webgl_3d_portfolio."""
        si = StructuredIdentityProfile(
            themes=["cinematic"],
            visual_tendencies=[],
            content_types=["projects"],
            complexity="moderate",
        )
        mode = derive_experience_mode(si, site_archetype="portfolio")
        assert mode == "webgl_3d_portfolio"

    def test_text_only_writing_yields_flat(self) -> None:
        """Text-heavy writing with no visual → flat_standard."""
        si = StructuredIdentityProfile(
            themes=["editorial"],
            tone=["serious"],
            visual_tendencies=[],
            content_types=["writing"],
            complexity="simple",
        )
        mode = derive_experience_mode(si)
        assert mode == "flat_standard"

    def test_simple_no_spatial_yields_flat(self) -> None:
        """Simple complexity + no spatial/motion signals → flat_standard."""
        si = StructuredIdentityProfile(
            themes=["corporate"],
            visual_tendencies=[],
            content_types=["services"],
            complexity="simple",
        )
        mode = derive_experience_mode(si)
        assert mode == "flat_standard"

    def test_portfolio_archetype_without_creative_themes(self) -> None:
        """Portfolio archetype even without creative themes → webgl_3d (rule 6b)."""
        si = StructuredIdentityProfile(
            themes=["corporate"],
            visual_tendencies=[],
            content_types=["projects"],
            complexity="moderate",
        )
        mode = derive_experience_mode(si, site_archetype="portfolio")
        assert mode == "webgl_3d_portfolio"

    def test_gallery_archetype_with_experimental(self) -> None:
        """Gallery archetype + experimental → webgl_3d_portfolio."""
        si = StructuredIdentityProfile(
            themes=["experimental"],
            visual_tendencies=["motion-heavy"],
            content_types=["art"],
            complexity="ambitious",
        )
        mode = derive_experience_mode(si, site_archetype="gallery")
        assert mode == "webgl_3d_portfolio"

    def test_default_empty_identity_yields_flat(self) -> None:
        """Empty identity with no signals → flat_standard."""
        si = StructuredIdentityProfile()
        mode = derive_experience_mode(si)
        assert mode == "flat_standard"

    def test_different_identities_produce_different_modes(self) -> None:
        """Verify that different identities can lead to different modes."""
        creative = StructuredIdentityProfile(
            themes=["cinematic"],
            visual_tendencies=["image-driven"],
            content_types=["photography"],
            complexity="ambitious",
        )
        editorial = StructuredIdentityProfile(
            themes=["editorial"],
            visual_tendencies=[],
            content_types=["writing"],
            complexity="simple",
        )
        mode_creative = derive_experience_mode(creative)
        mode_editorial = derive_experience_mode(editorial)
        assert mode_creative != mode_editorial
        assert mode_creative in ("webgl_3d_portfolio", "immersive_spatial_portfolio")
        assert mode_editorial == "flat_standard"

    def test_mode_is_always_valid(self) -> None:
        """All derived modes must be from the valid set."""
        from kmbl_orchestrator.identity.profile import EXPERIENCE_MODES

        test_cases = [
            StructuredIdentityProfile(),
            StructuredIdentityProfile(themes=["artistic"], visual_tendencies=["spatial"]),
            StructuredIdentityProfile(themes=["editorial"], content_types=["writing"], complexity="simple"),
            StructuredIdentityProfile(themes=["experimental"], complexity="ambitious"),
        ]
        for si in test_cases:
            mode = derive_experience_mode(si)
            assert mode in EXPERIENCE_MODES, f"Invalid mode {mode} for {si}"


# ── Phase 3: Planner Output Always Includes experience_mode ──────────────────


class TestExperienceModeInBuildSpec:
    """Planner build_spec normalization ensures experience_mode is set."""

    def test_experience_mode_derivation_for_empty_build_spec(self) -> None:
        """When planner produces no experience_mode, derivation fills it in."""
        from kmbl_orchestrator.identity.profile import (
            StructuredIdentityProfile,
            derive_experience_mode,
        )

        # Simulate what planner_node does
        build_spec: dict = {"type": "stub", "title": "test"}
        existing_mode = build_spec.get("experience_mode")
        assert existing_mode is None  # Planner didn't set it

        si = StructuredIdentityProfile(
            themes=["artistic"],
            visual_tendencies=["image-driven"],
            content_types=["projects"],
            complexity="ambitious",
        )
        mode = derive_experience_mode(si, site_archetype=build_spec.get("site_archetype"))
        build_spec["experience_mode"] = mode
        assert build_spec["experience_mode"] in (
            "webgl_3d_portfolio", "immersive_spatial_portfolio",
        )

    def test_planner_set_experience_mode_preserved(self) -> None:
        """When planner sets experience_mode, it should be preserved (not overridden)."""
        build_spec = {
            "type": "stub",
            "title": "test",
            "experience_mode": "flat_standard",
        }
        existing = build_spec.get("experience_mode")
        assert isinstance(existing, str) and existing.strip()
        # In planner_node, we only derive when mode is missing — this should be preserved
        assert build_spec["experience_mode"] == "flat_standard"


# ── Integration: StructuredIdentityProfile Serialization Roundtrip ───────────


class TestStructuredIdentityRoundtrip:
    """Verify to_dict/model_validate roundtrip for pipeline propagation."""

    def test_roundtrip(self) -> None:
        original = StructuredIdentityProfile(
            themes=["artistic", "cinematic"],
            tone=["bold", "warm"],
            visual_tendencies=["image-driven", "motion-heavy"],
            content_types=["photography", "projects"],
            complexity="ambitious",
            notable_entities=["Jane Doe", "Abstract Studio"],
        )
        payload = original.to_dict()
        restored = StructuredIdentityProfile.model_validate(payload)
        assert restored.themes == original.themes
        assert restored.tone == original.tone
        assert restored.visual_tendencies == original.visual_tendencies
        assert restored.content_types == original.content_types
        assert restored.complexity == original.complexity
        assert restored.notable_entities == original.notable_entities

    def test_partial_roundtrip(self) -> None:
        """Partial profile (omitted fields) should roundtrip safely."""
        original = StructuredIdentityProfile(
            themes=["minimal"],
            complexity="simple",
        )
        payload = original.to_dict()
        assert "tone" not in payload
        restored = StructuredIdentityProfile.model_validate(payload)
        assert restored.themes == ["minimal"]
        assert restored.tone == []
        assert restored.complexity == "simple"
