
"""Agregar autenticacion Google y verificacion email

Revision ID: 45b4a8d18dee
Revises: 5c3a3448a44b
Create Date: 2026-11-23 16:12:39.644032
"""

from alembic import op
import sqlalchemy as sa


revision = '45b4a8d18dee'
down_revision = '5c3a3448a44b'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    # Crear la tabla únicamente si todavía no existe.
    if 'pending_registrations' not in existing_tables:
        op.create_table(
            'pending_registrations',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('username', sa.String(length=60), nullable=False),
            sa.Column('email', sa.String(length=150), nullable=False),
            sa.Column('phone', sa.String(length=30), nullable=True),
            sa.Column('password_hash', sa.String(length=255), nullable=False),
            sa.Column('verification_code_hash', sa.String(length=255), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('email')
        )

    # Obtener las columnas actuales de users.
    inspector = sa.inspect(op.get_bind())
    existing_columns = {
        column['name']
        for column in inspector.get_columns('users')
    }

    with op.batch_alter_table('users', schema=None) as batch_op:

        if 'phone' not in existing_columns:
            batch_op.add_column(
                sa.Column('phone', sa.String(length=30), nullable=True)
            )

        if 'google_id' not in existing_columns:
            batch_op.add_column(
                sa.Column('google_id', sa.String(length=255), nullable=True)
            )

        if 'email_verified' not in existing_columns:
            batch_op.add_column(
                sa.Column(
                    'email_verified',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true()
                )
            )

    # Crear el índice únicamente si todavía no existe.
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {
        index['name']
        for index in inspector.get_indexes('users')
    }

    if 'ix_users_google_id' not in existing_indexes:
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.create_index(
                'ix_users_google_id',
                ['google_id'],
                unique=True
            )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    if 'users' in existing_tables:
        existing_columns = {
            column['name']
            for column in inspector.get_columns('users')
        }

        existing_indexes = {
            index['name']
            for index in inspector.get_indexes('users')
        }

        with op.batch_alter_table('users', schema=None) as batch_op:
            if 'ix_users_google_id' in existing_indexes:
                batch_op.drop_index('ix_users_google_id')

            for column in ('email_verified', 'google_id', 'phone'):
                if column in existing_columns:
                    batch_op.drop_column(column)

    if 'pending_registrations' in existing_tables:
        op.drop_table('pending_registrations')
