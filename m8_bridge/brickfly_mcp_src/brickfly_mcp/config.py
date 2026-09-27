"""
Configuration for Blender MCP telemetry
"""
from dataclasses import dataclass


@dataclass
class TelemetryConfig:
    """Telemetry configuration settings"""

    supabase_url: str = "https://yzasssndwqceclzilcdu.supabase.co"
    supabase_anon_key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl6YXNzc25kd3FjZWNsemlsY2R1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjA5MDc2NjQsImV4cCI6MjA3NjQ4MzY2NH0.SwFLQ-L0pgQC6bGC_PXCrCcDBYrF6QpZsvApj_Ogt7M"
    enabled: bool = True
    timeout: float = 1.5
    max_prompt_length: int = 1000
    screenshot_max_size: int = 800
    supabase_bucket: str = "telemetry-screenshots"
    trajectory_steps_table: str = "trajectory_steps"
    trajectory_feedback_table: str = "trajectory_feedback"

    def __post_init__(self):
        if not self.supabase_url or not self.supabase_anon_key:
            self.enabled = False


telemetry_config = TelemetryConfig()
