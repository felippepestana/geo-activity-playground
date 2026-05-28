import datetime

from geo_activity_playground.core.event_macro import (
    EventConfig,
    EventRules,
    EventStage,
    RuntimeContext,
    ScheduleWindow,
    StageStatus,
    TimelineBlock,
    iniciar_evento,
)


def _make_schedule_windows(start: datetime.datetime) -> dict[EventStage, ScheduleWindow]:
    return {
        EventStage.PRE_EVENTO: ScheduleWindow(
            start=start, end=start + datetime.timedelta(hours=8)
        ),
        EventStage.CHECK_IN_CIDADE: ScheduleWindow(
            start=start + datetime.timedelta(hours=8),
            end=start + datetime.timedelta(hours=12),
        ),
        EventStage.DESLOCAMENTO_PISTA: ScheduleWindow(
            start=start + datetime.timedelta(hours=12),
            end=start + datetime.timedelta(hours=16),
        ),
        EventStage.PROGRAMACAO_72H: ScheduleWindow(
            start=start + datetime.timedelta(hours=16),
            end=start + datetime.timedelta(hours=68),
        ),
        EventStage.ENCERRAMENTO_LOCAL: ScheduleWindow(
            start=start + datetime.timedelta(hours=68),
            end=start + datetime.timedelta(hours=70),
        ),
        EventStage.RETORNO_ORIGEM: ScheduleWindow(
            start=start + datetime.timedelta(hours=70),
            end=start + datetime.timedelta(hours=72),
        ),
    }


def _make_config(
    *,
    logistics_confirmed: bool = True,
    security_authorized: bool = True,
    available_resources: tuple[str, ...] = ("onibus", "kits", "transporte_reserva"),
) -> EventConfig:
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return EventConfig(
        duration_hours=72,
        origin_city="Recife",
        track_location="Pista Central",
        schedule_windows=_make_schedule_windows(start),
        teams=("Operações", "Segurança"),
        required_resources=("onibus", "kits"),
        available_resources=available_resources,
        rules=EventRules(min_participants=3, require_security_authorization=True),
        logistics_confirmed=logistics_confirmed,
        security_authorized=security_authorized,
    )


def _make_timeline() -> list[TimelineBlock]:
    return [
        TimelineBlock(
            block_id="briefing",
            name="Briefing inicial",
            planned_start_hour=0,
            planned_end_hour=2,
            responsible="Operações",
            location="Cidade",
        ),
        TimelineBlock(
            block_id="atividade_1",
            name="Atividade principal",
            planned_start_hour=2,
            planned_end_hour=10,
            responsible="Segurança",
            location="Pista",
            dependencies=("briefing",),
        ),
    ]


def test_iniciar_evento_happy_path() -> None:
    report = iniciar_evento(
        config=_make_config(),
        timeline=_make_timeline(),
        runtime=RuntimeContext(checked_in_participants=("A", "B", "C")),
    )

    assert report.blocked_stage is None
    assert report.return_completed is True
    assert report.stage_status[EventStage.RETORNO_ORIGEM] == StageStatus.CONCLUIDO
    assert len(report.executed_timeline) == 2


def test_iniciar_evento_blocks_on_low_check_in() -> None:
    report = iniciar_evento(
        config=_make_config(),
        timeline=_make_timeline(),
        runtime=RuntimeContext(checked_in_participants=("A", "B")),
    )

    assert report.blocked_stage == EventStage.CHECK_IN_CIDADE
    assert report.stage_status[EventStage.CHECK_IN_CIDADE] == StageStatus.BLOQUEADO
    assert report.return_completed is False
    assert report.executed_timeline == ()


def test_iniciar_evento_uses_transport_contingency() -> None:
    report = iniciar_evento(
        config=_make_config(),
        timeline=_make_timeline(),
        runtime=RuntimeContext(
            checked_in_participants=("A", "B", "C"),
            transport_available=False,
        ),
    )

    assert report.blocked_stage is None
    assert report.return_completed is True
    assert any("contingência de transporte reserva" in incident for incident in report.incidents)


def test_iniciar_evento_blocks_when_timeline_exceeds_duration() -> None:
    long_timeline = [
        TimelineBlock(
            block_id="longo",
            name="Atividade longa",
            planned_start_hour=10,
            planned_end_hour=80,
            responsible="Operações",
            location="Pista",
        )
    ]
    report = iniciar_evento(
        config=_make_config(),
        timeline=long_timeline,
        runtime=RuntimeContext(
            checked_in_participants=("A", "B", "C"),
            timeline_delays_hours={"longo": 5.0},
        ),
    )

    assert report.blocked_stage == EventStage.PROGRAMACAO_72H
    assert report.stage_status[EventStage.PROGRAMACAO_72H] == StageStatus.BLOQUEADO
