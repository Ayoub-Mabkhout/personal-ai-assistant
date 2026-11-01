"""Version-one wire format. Metric source values are never doubled for dumbbells."""
from datetime import datetime, date
from typing import Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Athlete(Model):
    name: str = Field(default='', max_length=120)
    height_cm: float | None = Field(default=None, gt=0, le=300)
    birth_date: date | None = None
    sex: Literal['male', 'female', 'unspecified'] = 'unspecified'
    units: Literal['metric', 'imperial'] = 'metric'
    goals: list[str] = Field(default_factory=list, max_length=20)
    context: str = Field(default='', max_length=8000)
    goal_weight_min_kg: float | None = Field(default=None,gt=0,le=500,validation_alias=AliasChoices('goal_weight_min_kg','target_weight_min_kg'))
    goal_weight_max_kg: float | None = Field(default=None,gt=0,le=500,validation_alias=AliasChoices('goal_weight_max_kg','target_weight_max_kg'))
    waist_height_ceiling: float | None = Field(default=None,gt=0,le=1)
    auto_coach_briefs: bool = False

    @model_validator(mode='after')
    def check(self):
        if self.goal_weight_min_kg and self.goal_weight_max_kg and self.goal_weight_max_kg<self.goal_weight_min_kg:
            raise ValueError('Personal weight goal range is reversed')
        return self


class Exercise(Model):
    name: str = Field(min_length=1, max_length=150)
    equipment: str = Field(default='', max_length=80)
    muscles: list[str] = Field(default_factory=list, max_length=20)
    aliases: list[str] = Field(default_factory=list, max_length=40)
    load_convention: Literal['total', 'per_hand', 'bodyweight', 'assisted', 'unknown'] = 'unknown'
    mode: Literal['strength', 'cardio', 'other'] = 'strength'
    movement: Literal['press','squat','hinge','row','pull','curl','extension','raise','lunge','core','run','walk','other'] = 'other'


class SetLog(Model):
    id: str = Field(min_length=1, max_length=100)
    exercise_id: str = Field(min_length=1, max_length=100)
    kind: Literal['working', 'warmup', 'drop', 'failure', 'note', 'other'] = 'working'
    raw_order: str = Field(default='', max_length=30)
    weight_kg: float | None = Field(default=None, ge=0, le=2000)
    reps: int | None = Field(default=None, ge=0, le=10000)
    rpe: float | None = Field(default=None, ge=0, le=10)
    rir: float | None = Field(default=None, ge=0, le=30)
    distance_m: float | None = Field(default=None, ge=0, le=1000000)
    seconds: float | None = Field(default=None, ge=0, le=604800)
    incline_percent: float | None = Field(default=None, ge=-30, le=100)
    elevation_gain_m: float | None = Field(default=None, ge=0, le=20000)
    completed: bool = True
    notes: str = Field(default='', max_length=8000)


class SessionBlock(Model):
    id: str = Field(min_length=1,max_length=100)
    kind: Literal['run','warmup','exercise','rest','other']
    exercise_id: str | None = Field(default=None,max_length=100)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    planned_seconds: int | None = Field(default=None,ge=0,le=86400)

    @model_validator(mode='after')
    def check(self):
        for value in (self.started_at,self.ended_at):
            if value and value.tzinfo is None: raise ValueError('Block timestamp needs timezone')
        if self.ended_at and (not self.started_at or self.ended_at<self.started_at):
            raise ValueError('Block ends before it starts')
        return self


class SessionChange(Model):
    id: str = Field(default='',max_length=100)
    at: datetime
    kind: Literal['swap','edit','shorter','rest','other','swap_day','edit_exercises','rest_move']
    reason: str = Field(min_length=1,max_length=2000,validation_alias=AliasChoices('reason','note'))
    from_template_id: str | None = Field(default=None,max_length=100)
    original_date: date | None = None
    new_date: date | None = None

    @model_validator(mode='after')
    def check(self):
        if self.at.tzinfo is None: raise ValueError('Session change needs timezone')
        return self


class Workout(Model):
    name: str = Field(min_length=1, max_length=200)
    started_at: str = Field(min_length=10, max_length=50)
    timezone: str = Field(default='UTC', max_length=100)
    duration_seconds: int = Field(default=0, ge=0, le=604800)
    status: Literal['draft', 'active', 'paused', 'completed', 'skipped', 'rest'] = 'draft'
    sprint_id: str | None = Field(default=None, max_length=100)
    template_id: str | None = Field(default=None, max_length=100)
    bodyweight_kg: float | None = Field(default=None, gt=0, le=500)
    sets: list[SetLog] = Field(default_factory=list, max_length=1000)
    blocks: list[SessionBlock] = Field(default_factory=list,max_length=1000)
    session_changes: list[SessionChange] = Field(default_factory=list,max_length=100)
    notes: str = Field(default='', max_length=16000)
    skip_reason: str = Field(default='', max_length=1000)
    recovery_adjusted: bool = False
    source: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def check(self):
        datetime.fromisoformat(self.started_at)
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try: ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError,ValueError): raise ValueError('Unknown workout timezone') from None
        ids = [s.id for s in self.sets]
        if len(set(ids)) != len(ids): raise ValueError('Duplicate set identifiers')
        return self


class Prescription(Model):
    exercise_id: str = Field(min_length=1, max_length=100)
    sets: int = Field(default=1, ge=0, le=30)
    min_reps: int = Field(default=5, ge=0, le=1000)
    max_reps: int = Field(default=8, ge=0, le=1000)
    rir: float | None = Field(default=None, ge=0, le=30)
    rest_seconds: int = Field(default=180, ge=0, le=1800)
    weight_kg: float | None = Field(default=None, ge=0, le=2000)
    distance_m: float | None = Field(default=None, gt=0, le=1000000)
    speed_kmh: float | None = Field(default=None, gt=0, le=60)
    estimated_seconds: int | None = Field(default=None,ge=0,le=86400)
    notes: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def check(self):
        if self.max_reps < self.min_reps: raise ValueError('Rep range is reversed')
        return self


class Template(Model):
    name: str = Field(min_length=1, max_length=200)
    exercises: list[Prescription] = Field(default_factory=list, max_length=100)
    notes: str = Field(default='', max_length=8000)
    planned_blocks: list[SessionBlock] = Field(default_factory=list,max_length=200)


class Sprint(Model):
    name: str = Field(min_length=1, max_length=200)
    phase: str = Field(min_length=1, max_length=100)
    start: date
    end: date | None = None
    status: Literal['planned', 'active', 'completed', 'cancelled'] = 'planned'
    goals: list[str] = Field(default_factory=list, max_length=20)
    success_criteria: list[str] = Field(default_factory=list, max_length=30)
    scheduled: list[dict] = Field(default_factory=list, max_length=100)
    cycle: list[str] = Field(default_factory=list,max_length=100)
    target_sessions: int | None = Field(default=None,ge=1,le=10000)
    extensions: list[dict] = Field(default_factory=list,max_length=100)
    constraints: str = Field(default='', max_length=8000)
    retrospective: str = Field(default='', max_length=16000)

    @model_validator(mode='after')
    def check(self):
        from .programs import add_months
        if self.end is None: self.end=add_months(self.start,4)
        if self.target_sessions is None: self.target_sessions=len(self.cycle) or len(self.scheduled) or 1
        if self.end < self.start: raise ValueError('Sprint end precedes start')
        for item in self.scheduled:
            if set(item) - {'date', 'template_id', 'notes'} or 'date' not in item:
                raise ValueError('Scheduled sessions need date, optional template_id and notes')
            if not self.start <= date.fromisoformat(item['date']) <= self.end:
                raise ValueError('Scheduled session is outside sprint')
        return self


class Measurement(Model):
    measured_at: datetime
    kind: Literal['bodyweight', 'waist']
    value: float = Field(gt=0, le=1000)
    unit: Literal['kg', 'cm']
    method: str = Field(default='', max_length=200)
    notes: str = Field(default='', max_length=2000)
    source: str = Field(default='manual', max_length=200)

    @model_validator(mode='after')
    def check(self):
        if self.measured_at.tzinfo is None: raise ValueError('Measurement needs timezone')
        if self.unit != ('kg' if self.kind == 'bodyweight' else 'cm'): raise ValueError('Incorrect unit')
        return self


class Recovery(Model):
    observed_at: datetime
    workout_id: str | None = Field(default=None, max_length=100)
    muscles: list[str] = Field(default_factory=list, max_length=20)
    soreness: int = Field(default=0, ge=0, le=10)
    fatigue: int = Field(default=0, ge=0, le=10)
    duration_hours: float | None = Field(default=None, ge=0, le=1000)
    pain: str = Field(default='', max_length=2000)
    notes: str = Field(default='', max_length=4000)

    @model_validator(mode='after')
    def check(self):
        if self.observed_at.tzinfo is None: raise ValueError('Recovery observation needs timezone')
        return self


class Photo(Model):
    captured_at: datetime
    blob_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    pose: Literal['front', 'side', 'back', 'other'] = 'front'
    state: Literal['relaxed', 'flexed', 'pumped'] = 'relaxed'
    conditions: str = Field(default='', max_length=2000)
    notes: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def check(self):
        if self.captured_at.tzinfo is None: raise ValueError('Photo needs timezone')
        return self


class Composition(Model):
    assessed_at: datetime
    photo_ids: list[str] = Field(min_length=1,max_length=6)
    low_percent: float = Field(ge=3,le=65)
    high_percent: float = Field(ge=3,le=65)
    method: Literal['visual_estimate'] = 'visual_estimate'
    model: str = Field(min_length=1,max_length=100)
    uncertainty: str = Field(min_length=1,max_length=4000)
    source_question: str = Field(min_length=1,max_length=100)

    @model_validator(mode='after')
    def check(self):
        if self.high_percent-self.low_percent<3: raise ValueError('Visual estimates need a broad range of at least 3 percentage points')
        if self.assessed_at.tzinfo is None: raise ValueError('Estimate needs timezone')
        return self


MODELS = dict(athlete=Athlete, exercise=Exercise, workout=Workout, template=Template,
              sprint=Sprint, measurement=Measurement, recovery=Recovery, photo=Photo,composition=Composition)


def validate(kind, data):
    if kind not in MODELS: raise ValueError('Unknown workout entity kind')
    return MODELS[kind].model_validate(data).model_dump(mode='json')


class Mutation(Model):
    mutation_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,100}$')
    kind: str
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    base_revision: int = Field(ge=0)
    deleted: bool = False
    data: dict = Field(default_factory=dict)
