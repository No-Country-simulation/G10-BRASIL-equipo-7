import type { DadosClinicos } from '../api/revisao'

const objeto = (valor: unknown): Record<string, unknown> => valor && typeof valor === 'object' && !Array.isArray(valor) ? valor as Record<string, unknown> : {}
const texto = (valor: unknown) => typeof valor === 'string' ? valor : ''
const nulo = (valor: string) => valor.trim() || null
export function iniciarDadosRevisao(valor: unknown) {
  const dados = objeto(valor), paciente = objeto(dados.paciente), medico = objeto(dados.medico_responsavel)
  return {
    nome: texto(paciente.nome), idade: typeof paciente.idade === 'number' ? String(paciente.idade) : '',
    medico: texto(medico.nome), crm: texto(medico.crm),
    medicamentos: (Array.isArray(dados.medicamentos) ? dados.medicamentos : []).map((item: unknown) => {
      const medicamento = objeto(item)
      return { nome: texto(medicamento.nome), dosagem: texto(medicamento.dosagem), posologia: texto(medicamento.posologia) }
    }),
    medicamentosNulos: dados.medicamentos == null,
    exame: texto(dados.exame_realizado), diagnostico: texto(dados.diagnostico_principal), cid: texto(dados.cid_sugerido),
  }
}
export type DadosFormulario = ReturnType<typeof iniciarDadosRevisao>
export function concluirDadosRevisao(dados: DadosFormulario): DadosClinicos {
  const idade = dados.idade.trim() === '' ? null : Number(dados.idade)
  if (idade !== null && (!Number.isSafeInteger(idade) || idade < 0)) throw Error('Informe uma idade inteira maior ou igual a zero, ou deixe em branco.')
  const nome = nulo(dados.nome), medico = nulo(dados.medico), crm = nulo(dados.crm)
  return {
    paciente: nome !== null || idade !== null ? { nome, idade } : null,
    medico_responsavel: medico || crm ? { nome: medico, crm } : null,
    medicamentos: dados.medicamentos.length ? dados.medicamentos.map((item) => ({ nome: nulo(item.nome), dosagem: nulo(item.dosagem), posologia: nulo(item.posologia) })) : dados.medicamentosNulos ? null : [],
    exame_realizado: nulo(dados.exame), diagnostico_principal: nulo(dados.diagnostico), cid_sugerido: nulo(dados.cid),
  }
}
