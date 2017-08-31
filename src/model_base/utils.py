import datetime
from falcon_exceptions import HTTPException
from distutils.util import strtobool
from sqlalchemy import not_
from sqlalchemy.orm import aliased


class ModelBase(object):

    _alias = None

    # Method for parse uri parameters
    @classmethod
    def param_parser(self, req, query=None):
        query = query if query else self.query
        try:
            # Order
            if ('sort' in req.params):
                sort_data = []
                _sort = req.params.pop('sort')
                _sort = [_sort] if isinstance(_sort, basestring) else _sort
                for s in _sort:
                    if (s[0] == '-'):
                        sort_data.append(getattr(self, s[1:]).desc())
                    else:
                        sort_data.append(getattr(self, s))
                query = query.order_by(*sort_data)
            # Attributes
            if ('fields' in req.params):
                fields_data = []
                _fields = req.params.pop('fields')
                _fields = [_fields] if isinstance(_fields, basestring) else _fields
                for f in _fields:
                    fields_data.append(getattr(self, f))
                query = query.with_entities(*fields_data)
            # Includes
            if ('includes' in req.params):
                _includes = req.params.pop('includes')
                _includes = [_includes] if isinstance(_includes, basestring) else _includes
                req.context['_rel'] = _includes
                for i in _includes:
                    inc_parts = i.split('.')
                    obj_inc = getattr(self, inc_parts[0])
                    if obj_inc.mapper.class_ == self:
                        self._alias = aliased(self, name="same%s" % self.__tablename__)
                        query = query.outerjoin(self._alias, self._alias.id == self.parentId)
                    else:
                        query = query.outerjoin(obj_inc)
            # Filtering
            if(req.params):
                _filters = req.params
                for k, v in _filters.iteritems():
                    if k not in ['limit', 'offset']:
                        query = self._eval_filter(v.encode('utf-8') if isinstance(v, str) else v, k, query)
            # Count
            if hasattr(self, 'id'):
                _count = query.group_by(getattr(self, 'id')).count()
            else:
                _count = query.count()
            # Limit
            _limit = 10
            if ('limit' in req.params):
                _limit = req.params.pop('limit')
                _limit = None if (_limit == 'all') else int(_limit)
            query = query.limit(_limit) if (_limit) else query
            # Offset
            _offset = 0
            if ('offset' in req.params):
                _offset = int(req.params.pop('offset'))
            query = query.offset(_offset)

            return query, _count, _limit, _offset, req
        except (ValueError, AttributeError) as e:
            raise HTTPException(400,
                dev_msg=str(e),
                user_msg="Unknown or bad field use in query parameters"
            )

    # Parse include query string
    @classmethod
    def parse_rel(self, item):
        dict = {}
        parts_item = item.split('.')
        if len(parts_item) > 1:
            sub_dict = self.parse_rel('.'.join(parts_item[1:]))
            dict.update({ parts_item[0]: sub_dict })
            return dict
        else:
            return {parts_item[0]: {}}

    # Merge all include items
    @classmethod
    def merge_rel(self, item, dict):
      for k, v in item.iteritems():
          if k not in dict:
            dict.update({k: v})
          else:
            self.merge_rel(v, dict[k])

    # Serialize includes
    @classmethod
    def serialize_rel(self, row, rel_ctx, sub_rel_ctx):
        rel_obj = getattr(row, rel_ctx)
        rel_dict = None

        if isinstance(rel_obj, list):
            rel_dict = [i.to_dict() for i in rel_obj]
            if sub_rel_ctx != {}:
                rel_dict = []
                for rel_item in rel_obj:
                    item_dict = rel_item.to_dict()
                    for k, v in sub_rel_ctx.iteritems():
                        sub_rel_dict = self.serialize_rel(rel_item, k, v)
                        item_dict.update({k: sub_rel_dict})
                    rel_dict.append(item_dict)
        elif rel_obj:
            rel_dict = rel_obj.to_dict()
            if sub_rel_ctx != {}:
                for k, v in sub_rel_ctx.iteritems():
                    sub_rel_dict = self.serialize_rel(rel_obj, k, v)
                    rel_dict.update({k: sub_rel_dict})

        return rel_dict

    # Serializing query output
    @classmethod
    def serialize_query(self, req, query):
        try:
            columns = query.column_descriptions
            data = []
            for row in query:
                if isinstance(row, self):
                    row_dict = row.to_dict()
                    if row.__mapper__.relationships.keys() and '_rel' in req.context:

                        req.context['_rel'].sort()
                        parse_rel_ctx = [self.parse_rel(i) for i in req.context['_rel']]

                        rel_ctx = parse_rel_ctx[0]
                        for item in parse_rel_ctx[1:]:
                            self.merge_rel(item, rel_ctx)

                        for rel in row.__mapper__.relationships.keys():
                            if hasattr(row, rel) and rel in rel_ctx:
                                dict_rel_obj = self.serialize_rel(row, rel, rel_ctx[rel])
                                row_dict.update({rel: dict_rel_obj})

                    data.append(row_dict)
                elif isinstance(row, tuple):
                    # Fetching all tuple items
                    _row = {}
                    for i in xrange(len(row)):
                        item = row[i]
                        if isinstance(item, self):
                            _row.update(item.to_dict())
                        else:
                            _row.update({
                                columns[i]['name'].encode('ascii', 'ignore'): item
                            })
                    data.append(_row)
            return data
        except (ValueError, AttributeError) as e:
            raise HTTPException(400,
                dev_msg=str(e),
                user_msg="Unknown or bad field use in query parameters"
            )

    @classmethod
    def count_all(self):
        return self.query.count()

    def update(self, **kwargs):
        """ Update fields """
        for k, v in kwargs.iteritems():
            if k != 'id' and hasattr(self, k) and v is not None:
                setattr(self, k, v)
        if hasattr(self, 'updated'):
            self.updated = datetime.datetime.now()

    # Eval filter
    @classmethod
    def _eval_filter(self, val, key, query):
        filter_parts = key.split('__')
        if len(filter_parts) > 1:
            key, operator = filter_parts
            sub_filter_parts = key.split('.')
            rel_cls = None
            if len(sub_filter_parts) > 1:
                for rel in self.__mapper__.relationships.items():
                    if rel[0] == sub_filter_parts[0]:
                        rel_cls = rel[1].mapper.class_
                        rel_cls = self._alias if rel_cls == self else rel_cls

                if not rel_cls:
                    raise HTTPException(400,
                        dev_msg="Unknown or bad field use in query parameters",
                        user_msg="Unknown or bad field use in query parameters"
                    )

            if operator == "eq":
                val = bool(strtobool(val)) if val in ['true', 'True', 'false', 'False'] else val
                val = None if val in ['None', 'none', 'Null', 'null'] else val
                if rel_cls:
                    query = query.filter(getattr(rel_cls, sub_filter_parts[1]) == val)
                else:
                    query = query.filter(getattr(self, key) == val)
            elif operator == "gt":
                if rel_cls:
                    query = query.filter(getattr(rel_cls, sub_filter_parts[1]) > val)
                else:
                    query = query.filter(getattr(self, key) > val)
            elif operator == "gte":
                if rel_cls:
                    query = query.filter(getattr(rel_cls, sub_filter_parts[1]) >= val)
                else:
                    query = query.filter(getattr(self, key) >= val)
            elif operator == "lt":
                if rel_cls:
                    query = query.filter(getattr(rel_cls, sub_filter_parts[1]) < val)
                else:
                    query = query.filter(getattr(self, key) < val)
            elif operator == "lte":
                if rel_cls:
                    query = query.filter(getattr(rel_cls, sub_filter_parts[1]) <= val)
                else:
                    query = query.filter(getattr(self, key) <= val)
            elif operator == "ne":
                val = bool(strtobool(val)) if val in ['true', 'True', 'false', 'False'] else val
                val = None if val in ['None', 'none', 'Null', 'null'] else val
                if rel_cls:
                    query = query.filter(getattr(rel_cls, sub_filter_parts[1]) != val)
                else:
                    query = query.filter(getattr(self, key) != val)
            elif operator == "not":
                val = bool(strtobool(val)) if val in ['true', 'True', 'false', 'False'] else val
                val = None if val in ['None', 'none', 'Null', 'null'] else val
                if rel_cls:
                    query = query.filter(not_(getattr(rel_cls, sub_filter_parts[1]) == val))
                else:
                    query = query.filter(not_(getattr(self, key) == val))
            elif operator == "range":
                if rel_cls:
                    query = query.filter(getattr(rel_cls, sub_filter_parts[1]).between(*val))
                else:
                    query = query.filter(getattr(self, key).between(*val))
            elif operator == "not_range":
                if rel_cls:
                    query = query.filter(not_(getattr(rel_cls, sub_filter_parts[1]).between(*val)))
                else:
                    query = query.filter(not_(getattr(self, key).between(*val)))
            elif operator == "in":
                val = [val] if isinstance(val, basestring) else val
                if rel_cls:
                    query = query.filter(getattr(rel_cls, sub_filter_parts[1]).in_(val))
                else:
                    query = query.filter(getattr(self, key).in_(val))
            elif operator == "not_in":
                val = [val] if isinstance(val, basestring) else val
                if rel_cls:
                    query = query.filter(not_(getattr(rel_cls, sub_filter_parts[1]).in_(val)))
                else:
                    query = query.filter(not_(getattr(self, key).in_(val)))
            elif operator == "like":
                val = '%{0}%'.format(val);
                if rel_cls:
                    query = query.filter(getattr(rel_cls, sub_filter_parts[1]).ilike(val))
                else:
                    query = query.filter(getattr(self, key).ilike(val))
            elif operator == "not_like":
                val = '%{0}%'.format(val);
                if rel_cls:
                    query = query.filter(not_(getattr(rel_cls, sub_filter_parts[1]).ilike(val)))
                else:
                    query = query.filter(not_(getattr(self, key).ilike(val)))
            else:
                raise HTTPException(400,
                    dev_msg="Unknown or bad field use in query parameters",
                    user_msg="Unknown or bad field use in query parameters"
                )
        else:
            sub_filter_parts = key.split('.')
            rel_cls = None
            if len(sub_filter_parts) > 1:
                for rel in self.__mapper__.relationships.items():
                    if rel[0] == sub_filter_parts[0]:
                        rel_cls = rel[1].mapper.class_
                        rel_cls = self._alias if rel_cls == self else rel_cls

                if not rel_cls:
                    raise HTTPException(400,
                        dev_msg="Unknown or bad field use in query parameters",
                        user_msg="Unknown or bad field use in query parameters"
                    )

            val = bool(strtobool(val)) if val in ['true', 'True', 'false', 'False'] else val
            val = None if val in ['None', 'none', 'Null', 'null'] else val
            if rel_cls:
                query = query.filter(getattr(rel_cls, sub_filter_parts[1]) == val)
            else:
                query = query.filter(getattr(self, key) == val)

        return query
