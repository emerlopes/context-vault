"""Default section templates per note type (spec §7–§11)."""

from __future__ import annotations

from ..models.notes import NoteType

TEMPLATES: dict[NoteType, list[str]] = {
    NoteType.DOMAIN: [
        "Visão geral", "Conceitos", "Sistemas e serviços", "Processos", "Regras de negócio",
        "Integrações", "Responsáveis", "Dependências", "Dúvidas conhecidas", "Histórico", "Referências",
    ],
    NoteType.PROJECT: [
        "Visão geral", "Objetivos", "Escopo", "Status atual", "Entregas", "Marcos", "Riscos", "Bloqueios",
        "Dependências", "Decisões", "Pessoas envolvidas", "Próximos passos", "Histórico de atualizações",
        "Referências",
    ],
    NoteType.ARCHITECTURE: [
        "Contexto", "Componentes envolvidos", "Funcionamento", "Contratos", "Dependências", "Restrições",
        "Riscos", "Decisões relacionadas", "Histórico", "Referências",
    ],
    NoteType.ARCHITECTURE_DECISION: [
        "Contexto", "Problema", "Alternativas consideradas", "Decisão", "Justificativa", "Consequências",
        "Riscos", "Histórico", "Referências",
    ],
    NoteType.PERSON: [
        "Função", "Responsabilidades", "Projetos", "Sistemas sob responsabilidade", "Acordos", "Histórico",
        "Referências",
    ],
    NoteType.TEAM: ["Visão geral", "Membros", "Responsabilidades", "Sistemas", "Projetos", "Histórico", "Referências"],
    NoteType.MEETING: [
        "Objetivo", "Participantes", "Contexto anterior", "Pauta", "Discussões", "Decisões", "Pendências",
        "Dúvidas em aberto", "Próximos passos", "Referências",
    ],
}
