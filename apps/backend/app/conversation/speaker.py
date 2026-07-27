from __future__ import annotations

import re

from apps.backend.app.conversation.schemas import SpeakerRole, SpeakerRoleEstimate


class SpeakerRoleEstimator:
    """Conservative role estimation without biometric identity or voiceprints."""

    _third_person = re.compile(
        r"(?iu)\b(?:скажи\s+(?:ему|ей|им)|спроси\s+(?:его|её|их)|"
        r"он\s+(?:сказал|говорит)|она\s+(?:сказала|говорит)|мы\s+с\s+ним|мы\s+с\s+ней)\b"
    )

    def estimate(
        self,
        transcript: str,
        *,
        participant_mode: str,
        addressedness: float,
        echo: bool,
        recent_primary: bool = False,
    ) -> SpeakerRoleEstimate:
        if echo:
            return SpeakerRoleEstimate(
                role=SpeakerRole.ASSISTANT_ECHO,
                confidence=0.99,
                reasons=["playback_similarity"],
            )
        if participant_mode == "one_to_one":
            return SpeakerRoleEstimate(
                role=SpeakerRole.PRIMARY,
                confidence=0.9,
                reasons=["one_to_one_prior"],
            )
        if addressedness >= 0.86:
            return SpeakerRoleEstimate(
                role=SpeakerRole.PRIMARY,
                confidence=0.78,
                reasons=["direct_address"],
            )
        if self._third_person.search(transcript):
            return SpeakerRoleEstimate(
                role=SpeakerRole.OTHER,
                confidence=0.72,
                reasons=["third_person_conversation"],
            )
        if recent_primary:
            return SpeakerRoleEstimate(
                role=SpeakerRole.UNKNOWN,
                confidence=0.58,
                reasons=["recent_primary_continuity", "insufficient_evidence"],
            )
        return SpeakerRoleEstimate(
            role=SpeakerRole.UNKNOWN,
            confidence=0.62,
            reasons=["group_unknown_prior", "insufficient_evidence"],
        )
