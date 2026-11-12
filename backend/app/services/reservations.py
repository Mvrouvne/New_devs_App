from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List
from zoneinfo import ZoneInfo

async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int, year: int) -> Decimal:
    """
    Calculates revenue for a specific month, using the property's local timezone
    to define the month (e.g. a 23:30 UTC check-in on Feb 29 is March 1 in Paris).
    """
    from sqlalchemy import text
    from app.core.database_pool import db_pool

    if not db_pool.session_factory:
        await db_pool.initialize()
    if not db_pool.session_factory:
        raise Exception("Database pool not available")

    async with db_pool.get_session() as session:
        tz_row = (await session.execute(
            text("SELECT timezone FROM properties WHERE id = :property_id AND tenant_id = :tenant_id"),
            {"property_id": property_id, "tenant_id": tenant_id},
        )).first()
        if not tz_row:
            return Decimal('0')

        # Month boundaries at local midnight in the property's timezone (timezone-aware)
        tz = ZoneInfo(tz_row.timezone or "UTC")
        start_date = datetime(year, month, 1, tzinfo=tz)
        if month < 12:
            end_date = datetime(year, month + 1, 1, tzinfo=tz)
        else:
            end_date = datetime(year + 1, 1, 1, tzinfo=tz)

        result = await session.execute(
            text("""
                SELECT SUM(total_amount) AS total
                FROM reservations
                WHERE property_id = :property_id
                AND tenant_id = :tenant_id
                AND check_in_date >= :start_date
                AND check_in_date < :end_date
            """),
            {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        total = result.scalar()
        return Decimal(str(total)) if total is not None else Decimal('0')

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    try:
        # Use the shared, module-level pool instead of creating a new engine per request
        from app.core.database_pool import db_pool

        # Initialize pool once (lazily)
        if not db_pool.session_factory:
            await db_pool.initialize()
        
        if db_pool.session_factory:
            async with db_pool.get_session() as session:
                # Use SQLAlchemy text for raw SQL
                from sqlalchemy import text
                
                query = text("""
                    SELECT 
                        property_id,
                        SUM(total_amount) as total_revenue,
                        COUNT(*) as reservation_count
                    FROM reservations 
                    WHERE property_id = :property_id AND tenant_id = :tenant_id
                    GROUP BY property_id
                """)
                
                result = await session.execute(query, {
                    "property_id": property_id, 
                    "tenant_id": tenant_id
                })
                row = result.fetchone()
                
                if row:
                    total_revenue = Decimal(str(row.total_revenue))
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": str(total_revenue),
                        "currency": "USD", 
                        "count": row.reservation_count
                    }
                else:
                    # No reservations found for this property
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": "0.00",
                        "currency": "USD",
                        "count": 0
                    }
        else:
            raise Exception("Database pool not available")
            
    except Exception as e:
        # Never fall back to fabricated revenue figures: surface the failure instead
        # so clients are not shown numbers that don't come from their data.
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")
        raise
