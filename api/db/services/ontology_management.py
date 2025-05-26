from db_models import OntologyVersion, OntologyAuditLog, EntityVersion, EntityAuditLog
from db.services import get_session
from common.utils import generate_version_hash

class OntologyManagementService:
    @classmethod
    def create_ontology_version(cls, version_data):
        with get_session() as session:
            version_hash = generate_version_hash(version_data)
            ontology_version = OntologyVersion.create(
                version_number=version_data['version_number'],
                status='draft',
                creator=version_data['creator'],
                created_time=int(time.time() * 1000)
            )
            return ontology_version

    @classmethod
    def compare_ontology_versions(cls, base_version_id, new_version_id):
        base_version = OntologyVersion.get_by_id(base_version_id)
        new_version = OntologyVersion.get_by_id(new_version_id)
        
        return {
            'version_diff': base_version.version_number != new_version.version_number,
            'entity_changes': {
                'added': [ev.id for ev in new_version.entity_versions if ev not in base_version.entity_versions],
                'removed': [ev.id for ev in base_version.entity_versions if ev not in new_version.entity_versions]
            }
        }

    @classmethod
    def approve_ontology_version(cls, version_id, action, comment, operator):
        with get_session() as session:
            ontology_version = OntologyVersion.get_by_id(version_id)
            ontology_version.status = 'approved' if action == 'approve' else 'rejected'
            ontology_version.approver = operator
            ontology_version.approved_time = int(time.time() * 1000)
            ontology_version.save()
            
            OntologyAuditLog.create(
                version=ontology_version,
                action=action,
                comment=comment,
                operator=operator,
                review_time=int(time.time() * 1000)
            )
            return ontology_version

class EntityManagementService:
    @classmethod
    def create_entity_version(cls, entity_data):
        with get_session() as session:
            version_hash = generate_version_hash(entity_data)
            entity_version = EntityVersion.create(
                entity_id=entity_data['entity_id'],
                entity_type=entity_data['entity_type'],
                properties=entity_data['properties'],
                version_hash=version_hash,
                ontology_version=entity_data['ontology_version_id']
            )
            return entity_version

    @classmethod
    def compare_entity_versions(cls, base_version_id, new_version_id):
        base_version = EntityVersion.get_by_id(base_version_id)
        new_version = EntityVersion.get_by_id(new_version_id)
        
        diff = {
            'entity_type_changed': base_version.entity_type != new_version.entity_type,
            'property_changes': {
                'added': [k for k in new_version.properties if k not in base_version.properties],
                'removed': [k for k in base_version.properties if k not in new_version.properties],
                'modified': [k for k in base_version.properties 
                           if k in new_version.properties and base_version.properties[k] != new_version.properties[k]]
            }
        }
        return diff

    @classmethod
    def approve_entity_version(cls, version_id, action, comment, operator):
        with get_session() as session:
            entity_version = EntityVersion.get_by_id(version_id)
            entity_version.status = 'approved' if action == 'approve' else 'rejected'
            entity_version.save()
            
            EntityAuditLog.create(
                version=entity_version,
                action=action,
                comment=comment,
                operator=operator,
                review_time=int(time.time() * 1000)
            )
            return entity_version