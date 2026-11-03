"""
Feedback module service for CRUD operations
"""
from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import Session, select, func, case

from app.models.feedback import FeedbackModule
from app.schemas.feedback import (
    FeedbackModuleCreate,
    FeedbackModuleUpdate,
    FeedbackModuleTreeNode,
    FeedbackModuleReorderItem,
)
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.logger import logger


class FeedbackModuleService:
    """Feedback module CRUD service"""

    @staticmethod
    def get_module_by_id(session: Session, module_id: int) -> FeedbackModule:
        """
        Get a module by ID

        Args:
            session: Database session
            module_id: Module ID

        Returns:
            FeedbackModule

        Raises:
            NotFoundException: If module not found
        """
        module = session.get(FeedbackModule, module_id)
        if not module:
            raise NotFoundException(f"Feedback module with ID {module_id} not found")
        return module

    @staticmethod
    def get_all_modules(session: Session) -> List[FeedbackModule]:
        """
        Get all feedback modules (flat list)

        Args:
            session: Database session

        Returns:
            List of all modules
        """
        # MySQL doesn't support NULLS FIRST, use CASE WHEN instead
        # Sort parents (NULL parent_id) first, then children
        statement = select(FeedbackModule).order_by(
            case(
                (FeedbackModule.parent_id.is_(None), 0),
                else_=1
            ),
            FeedbackModule.parent_id.asc(),
            FeedbackModule.sort_order.asc()
        )
        modules = session.exec(statement).all()
        return list(modules)

    @staticmethod
    def get_modules_tree(session: Session, include_inactive: bool = False) -> List[FeedbackModuleTreeNode]:
        """
        Get modules as a tree structure

        Args:
            session: Database session
            include_inactive: Whether to include inactive modules

        Returns:
            List of parent modules with children nested
        """
        # Build query
        statement = select(FeedbackModule)
        if not include_inactive:
            statement = statement.where(FeedbackModule.is_active == True)
        statement = statement.order_by(FeedbackModule.sort_order.asc())

        all_modules = session.exec(statement).all()

        # Build tree structure
        parent_modules = []
        children_map = {}

        for module in all_modules:
            if module.parent_id is None:
                # This is a parent module
                parent_modules.append(FeedbackModuleTreeNode(
                    id=module.id,
                    name=module.name,
                    parent_id=None,
                    sort_order=module.sort_order,
                    is_active=module.is_active,
                    children=[]
                ))
            else:
                # This is a child module, group by parent_id
                if module.parent_id not in children_map:
                    children_map[module.parent_id] = []
                children_map[module.parent_id].append(FeedbackModuleTreeNode(
                    id=module.id,
                    name=module.name,
                    parent_id=module.parent_id,
                    sort_order=module.sort_order,
                    is_active=module.is_active,
                    children=[]
                ))

        # Attach children to parents
        for parent in parent_modules:
            if parent.id in children_map:
                parent.children = children_map[parent.id]

        return parent_modules

    @staticmethod
    def create_module(session: Session, data: FeedbackModuleCreate) -> FeedbackModule:
        """
        Create a new feedback module

        Args:
            session: Database session
            data: Module creation data

        Returns:
            Created module

        Raises:
            NotFoundException: If parent module not found
            BadRequestException: If trying to create third-level module
        """
        # Validate parent module if specified
        if data.parent_id is not None:
            parent = session.get(FeedbackModule, data.parent_id)
            if not parent:
                raise NotFoundException(f"Parent module with ID {data.parent_id} not found")
            # Check that parent is a top-level module (no third-level modules)
            if parent.parent_id is not None:
                raise BadRequestException("Cannot create third-level modules. Only two levels are supported.")

        # Create module
        module = FeedbackModule(
            name=data.name,
            parent_id=data.parent_id,
            sort_order=data.sort_order,
            is_active=data.is_active,
        )

        session.add(module)
        session.commit()
        session.refresh(module)

        logger.info(f"Feedback module created: ID={module.id}, Name={module.name}, Parent={module.parent_id}")
        return module

    @staticmethod
    def update_module(session: Session, module_id: int, data: FeedbackModuleUpdate) -> FeedbackModule:
        """
        Update a feedback module

        Args:
            session: Database session
            module_id: Module ID
            data: Module update data

        Returns:
            Updated module

        Raises:
            NotFoundException: If module not found
            BadRequestException: If update would create invalid structure
        """
        module = session.get(FeedbackModule, module_id)
        if not module:
            raise NotFoundException(f"Feedback module with ID {module_id} not found")

        # Validate parent_id change if specified
        if data.parent_id is not None and data.parent_id != module.parent_id:
            if data.parent_id == module_id:
                raise BadRequestException("A module cannot be its own parent")

            parent = session.get(FeedbackModule, data.parent_id)
            if not parent:
                raise NotFoundException(f"Parent module with ID {data.parent_id} not found")
            if parent.parent_id is not None:
                raise BadRequestException("Cannot set a child module as parent. Only top-level modules can be parents.")

        # Update fields
        if data.name is not None:
            module.name = data.name
        if data.parent_id is not None:
            module.parent_id = data.parent_id
        if data.sort_order is not None:
            module.sort_order = data.sort_order
        if data.is_active is not None:
            module.is_active = data.is_active

        module.updated_at = datetime.now(timezone.utc)

        session.add(module)
        session.commit()
        session.refresh(module)

        logger.info(f"Feedback module updated: ID={module_id}, Name={module.name}")
        return module

    @staticmethod
    def delete_module(session: Session, module_id: int) -> None:
        """
        Delete a feedback module

        Note: Due to ON DELETE CASCADE, deleting a parent will also delete all its children

        Args:
            session: Database session
            module_id: Module ID

        Raises:
            NotFoundException: If module not found
        """
        module = session.get(FeedbackModule, module_id)
        if not module:
            raise NotFoundException(f"Feedback module with ID {module_id} not found")

        session.delete(module)
        session.commit()

        logger.info(f"Feedback module deleted: ID={module_id}, Name={module.name}")

    @staticmethod
    def reorder_modules(session: Session, updates: List[FeedbackModuleReorderItem]) -> List[FeedbackModule]:
        """
        Batch update module sort orders

        Args:
            session: Database session
            updates: List of module ID and new sort_order pairs

        Returns:
            List of updated modules

        Raises:
            NotFoundException: If any module not found
        """
        updated_modules = []

        for item in updates:
            module = session.get(FeedbackModule, item.id)
            if not module:
                raise NotFoundException(f"Feedback module with ID {item.id} not found")

            module.sort_order = item.sort_order
            module.updated_at = datetime.now(timezone.utc)
            session.add(module)
            updated_modules.append(module)

        session.commit()

        # Refresh all modules
        for module in updated_modules:
            session.refresh(module)

        logger.info(f"Reordered {len(updates)} feedback modules")
        return updated_modules

    @staticmethod
    def get_module_name(session: Session, module_id: Optional[int]) -> Optional[str]:
        """
        Get module name by ID (for joining with feedback)

        Args:
            session: Database session
            module_id: Module ID

        Returns:
            Module name or None
        """
        if module_id is None:
            return None

        module = session.get(FeedbackModule, module_id)
        return module.name if module else None
