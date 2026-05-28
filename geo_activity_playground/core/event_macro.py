import dataclasses
import datetime
import enum
from collections.abc import Iterable

MACRO_NAME = "Iniciar Evento"


class StageStatus(enum.StrEnum):
    NAO_INICIADO = "nao_iniciado"
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDO = "concluido"
    BLOQUEADO = "bloqueado"


class EventStage(enum.StrEnum):
    PRE_EVENTO = "pre_evento"
    CHECK_IN_CIDADE = "check_in_cidade"
    DESLOCAMENTO_PISTA = "deslocamento_pista"
    PROGRAMACAO_72H = "programacao_72h"
    ENCERRAMENTO_LOCAL = "encerramento_local"
    RETORNO_ORIGEM = "retorno_origem"


@dataclasses.dataclass(frozen=True)
class ScheduleWindow:
    start: datetime.datetime
    end: datetime.datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            msg = "Schedule window must have end after start."
            raise ValueError(msg)


@dataclasses.dataclass(frozen=True)
class EventRules:
    min_participants: int
    require_security_authorization: bool = True


@dataclasses.dataclass(frozen=True)
class ContingencyPlan:
    allow_transport_fallback: bool = True
    allow_weather_replanning: bool = True


@dataclasses.dataclass(frozen=True)
class TimelineBlock:
    block_id: str
    name: str
    planned_start_hour: float
    planned_end_hour: float
    responsible: str
    location: str
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.planned_end_hour <= self.planned_start_hour:
            msg = "Timeline block must have end after start."
            raise ValueError(msg)


@dataclasses.dataclass(frozen=True)
class EventConfig:
    duration_hours: int
    origin_city: str
    track_location: str
    schedule_windows: dict[EventStage, ScheduleWindow]
    teams: tuple[str, ...]
    required_resources: tuple[str, ...]
    available_resources: tuple[str, ...]
    rules: EventRules
    logistics_confirmed: bool = True
    security_authorized: bool = True
    contingency: ContingencyPlan = dataclasses.field(default_factory=ContingencyPlan)


@dataclasses.dataclass(frozen=True)
class RuntimeContext:
    checked_in_participants: tuple[str, ...]
    transport_available: bool = True
    weather_safe: bool = True
    timeline_delays_hours: dict[str, float] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class EventLogEntry:
    timestamp: datetime.datetime
    stage: EventStage
    event: str
    details: str


@dataclasses.dataclass(frozen=True)
class ExecutedTimelineBlock:
    block_id: str
    name: str
    responsible: str
    location: str
    planned_start_hour: float
    planned_end_hour: float
    actual_start_hour: float
    actual_end_hour: float
    status: StageStatus


@dataclasses.dataclass(frozen=True)
class MacroExecutionReport:
    macro_name: str
    stage_status: dict[EventStage, StageStatus]
    blocked_stage: EventStage | None
    executed_timeline: tuple[ExecutedTimelineBlock, ...]
    incidents: tuple[str, ...]
    event_log: tuple[EventLogEntry, ...]
    return_completed: bool


def iniciar_evento(
    config: EventConfig,
    timeline: Iterable[TimelineBlock],
    runtime: RuntimeContext,
) -> MacroExecutionReport:
    orchestrator = _EventOrchestrator(config=config, timeline=list(timeline), runtime=runtime)
    return orchestrator.run()


class _EventOrchestrator:
    def __init__(
        self,
        *,
        config: EventConfig,
        timeline: list[TimelineBlock],
        runtime: RuntimeContext,
    ) -> None:
        self._config = config
        self._timeline = sorted(timeline, key=lambda block: block.planned_start_hour)
        self._runtime = runtime
        self._stage_status = dict.fromkeys(
            self._ordered_stages(), StageStatus.NAO_INICIADO
        )
        self._blocked_stage: EventStage | None = None
        self._incidents: list[str] = []
        self._event_log: list[EventLogEntry] = []
        self._executed_timeline: list[ExecutedTimelineBlock] = []

    @staticmethod
    def _ordered_stages() -> tuple[EventStage, ...]:
        return (
            EventStage.PRE_EVENTO,
            EventStage.CHECK_IN_CIDADE,
            EventStage.DESLOCAMENTO_PISTA,
            EventStage.PROGRAMACAO_72H,
            EventStage.ENCERRAMENTO_LOCAL,
            EventStage.RETORNO_ORIGEM,
        )

    def run(self) -> MacroExecutionReport:
        self._validate_config()
        for stage in self._ordered_stages():
            if not self._execute_stage(stage):
                break

        return MacroExecutionReport(
            macro_name=MACRO_NAME,
            stage_status=dict(self._stage_status),
            blocked_stage=self._blocked_stage,
            executed_timeline=tuple(self._executed_timeline),
            incidents=tuple(self._incidents),
            event_log=tuple(self._event_log),
            return_completed=(
                self._stage_status[EventStage.RETORNO_ORIGEM] == StageStatus.CONCLUIDO
            ),
        )

    def _validate_config(self) -> None:
        if self._config.duration_hours <= 0:
            msg = "Event duration must be positive."
            raise ValueError(msg)
        if not self._config.origin_city:
            msg = "Origin city is required."
            raise ValueError(msg)
        if not self._config.track_location:
            msg = "Track location is required."
            raise ValueError(msg)
        if len(self._config.teams) == 0:
            msg = "At least one team must be configured."
            raise ValueError(msg)

        schedule_windows = self._config.schedule_windows
        for stage in self._ordered_stages():
            if stage not in schedule_windows:
                msg = f"Missing schedule window for stage '{stage}'."
                raise ValueError(msg)

        for previous, current in zip(self._ordered_stages(), self._ordered_stages()[1:]):
            if schedule_windows[current].start < schedule_windows[previous].end:
                msg = (
                    "Schedule windows must be ordered and non-overlapping "
                    f"('{previous}' before '{current}')."
                )
                raise ValueError(msg)

    def _execute_stage(self, stage: EventStage) -> bool:
        self._stage_status[stage] = StageStatus.EM_ANDAMENTO
        self._append_log(stage, "stage_started", f"Iniciando etapa {stage}.")

        validation_error = self._validate_stage(stage)
        if validation_error:
            self._block_stage(stage, validation_error)
            return False

        if stage == EventStage.PROGRAMACAO_72H:
            timeline_error = self._execute_timeline()
            if timeline_error:
                self._block_stage(stage, timeline_error)
                return False

        self._stage_status[stage] = StageStatus.CONCLUIDO
        self._append_log(stage, "stage_completed", f"Etapa {stage} concluída.")
        return True

    def _validate_stage(self, stage: EventStage) -> str | None:
        if stage == EventStage.PRE_EVENTO:
            if not self._config.logistics_confirmed:
                return "Logística não confirmada."
            missing = set(self._config.required_resources) - set(
                self._config.available_resources
            )
            if missing:
                missing_list = ", ".join(sorted(missing))
                return f"Recursos obrigatórios ausentes: {missing_list}."
            if self._config.rules.require_security_authorization:
                if not self._config.security_authorized:
                    return "Autorização de segurança ausente."

        if stage == EventStage.CHECK_IN_CIDADE:
            if len(self._runtime.checked_in_participants) < self._config.rules.min_participants:
                return "Participantes insuficientes no check-in."

        if stage == EventStage.DESLOCAMENTO_PISTA and not self._runtime.transport_available:
            has_fallback = "transporte_reserva" in self._config.available_resources
            if self._config.contingency.allow_transport_fallback and has_fallback:
                self._append_incident(
                    stage,
                    "Falha no transporte principal; contingência de transporte reserva acionada.",
                )
            else:
                return "Falha de transporte sem contingência disponível."

        if stage == EventStage.PROGRAMACAO_72H and not self._runtime.weather_safe:
            if self._config.contingency.allow_weather_replanning:
                self._append_incident(
                    stage,
                    "Condição climática adversa; replanejamento da agenda aplicado.",
                )
            else:
                return "Condição climática insegura sem contingência."

        return None

    def _execute_timeline(self) -> str | None:
        completed_blocks: dict[str, float] = {}
        for block in self._timeline:
            if any(dependency not in completed_blocks for dependency in block.dependencies):
                return f"Dependências não concluídas para bloco '{block.block_id}'."

            duration = block.planned_end_hour - block.planned_start_hour
            delay = self._runtime.timeline_delays_hours.get(block.block_id, 0.0)
            dependency_end = max(
                [completed_blocks[dependency] for dependency in block.dependencies],
                default=0.0,
            )
            actual_start = max(block.planned_start_hour + delay, dependency_end)
            actual_end = actual_start + duration

            if actual_end > float(self._config.duration_hours):
                return (
                    f"Bloco '{block.block_id}' extrapola a duração máxima "
                    f"de {self._config.duration_hours} horas."
                )

            if delay > 0:
                self._append_incident(
                    EventStage.PROGRAMACAO_72H,
                    f"Atraso de {delay:.2f}h no bloco '{block.block_id}' com replanejamento.",
                )

            self._executed_timeline.append(
                ExecutedTimelineBlock(
                    block_id=block.block_id,
                    name=block.name,
                    responsible=block.responsible,
                    location=block.location,
                    planned_start_hour=block.planned_start_hour,
                    planned_end_hour=block.planned_end_hour,
                    actual_start_hour=actual_start,
                    actual_end_hour=actual_end,
                    status=StageStatus.CONCLUIDO,
                )
            )
            completed_blocks[block.block_id] = actual_end

        return None

    def _block_stage(self, stage: EventStage, reason: str) -> None:
        self._stage_status[stage] = StageStatus.BLOQUEADO
        self._blocked_stage = stage
        self._append_incident(stage, reason)
        self._append_log(stage, "stage_blocked", reason)

    def _append_incident(self, stage: EventStage, reason: str) -> None:
        self._incidents.append(reason)
        self._append_log(stage, "incident", reason)

    def _append_log(self, stage: EventStage, event: str, details: str) -> None:
        self._event_log.append(
            EventLogEntry(
                timestamp=datetime.datetime.now(datetime.UTC),
                stage=stage,
                event=event,
                details=details,
            )
        )
