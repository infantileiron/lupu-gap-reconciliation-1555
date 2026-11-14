import {request} from './client';import type {ConservationReview} from '../types/entities';
export const list=()=>request<ConservationReview[]>('/conservation');
export const detail=(id:string)=>request<ConservationReview>('/conservation/'+id);
export const create=(data:unknown)=>request<ConservationReview>('/conservation','POST',data);
