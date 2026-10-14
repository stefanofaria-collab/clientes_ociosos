"""Barreira de segurança: o SMTP é EXCLUSIVAMENTE para contatos internos.

A lista de e-mails dos clientes é conteúdo do relatório e NUNCA é destino.
A validação acontece tanto ao salvar configurações quanto no envio SMTP.
"""
import re
from email.utils import getaddresses
from app import settings as s


ADDRESS_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,63}\Z")


def internal_domains():
    """Domínios permitidos, definidos no .env; padrão conservador."""
    return tuple(x for x in s.INTERNAL_EMAIL_DOMAINS if x)


def validate_internal_email(value, contacts=()):
    email = str(value).strip().lower()
    domains = internal_domains()
    if not ADDRESS_PATTERN.fullmatch(email) or email.rsplit('@', 1)[-1] not in domains:
        permitted = ', '.join('@' + d for d in domains) or '(nenhum)'
        raise ValueError(f'Envio exclusivamente interno. Destinatários permitidos: {permitted}.')
    if email in {str(x).strip().lower() for x in contacts if x}:
        raise ValueError('Destinatário bloqueado: endereço também cadastrado como e-mail de cliente.')
    return email


def customer_contacts(items):
    return {str(row.get('email', '')).strip().lower() for row in items if row.get('email')}


def smtp_envelope_recipient(message):
    """Ignora quaisquer campos de endereço além de um único To validado."""
    if message.get_all('Cc') or message.get_all('Bcc') or message.get_all('Resent-To'):
        raise ValueError('SMTP interno não permite Cc, Bcc ou reenvio.')
    to_headers = message.get_all('To', [])
    recipients = getaddresses(to_headers)
    if len(recipients) != 1:
        raise ValueError('SMTP interno requer um único destinatário aprovado por mensagem.')
    return validate_internal_email(recipients[0][1])
